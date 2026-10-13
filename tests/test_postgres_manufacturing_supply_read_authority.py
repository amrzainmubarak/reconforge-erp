"""Native fractional demand must authorize every retained exposed money value."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from reconforge.auth.policy import evaluate_principal_access
from reconforge.domain.finance_posting import FinancePostingError, canonical_json, digest_payload
from reconforge.domain.manufacturing_execution import BomPreparation
from reconforge.domain.manufacturing_execution_v2 import RoutingPreparation
from reconforge.domain.procurement_partial import MultilineProcurementPreparation, ProcurementOrderLine
from reconforge.domain.procurement_sourcing import RequisitionPreparation, SupplierQuotationPreparation
from reconforge.infrastructure.postgres_manufacturing_execution import PostgresManufacturingExecutionRepository
from reconforge.infrastructure.postgres_manufacturing_execution_v2 import PostgresManufacturingExecutionV2Repository
from reconforge.infrastructure.postgres_manufacturing_supply_plan import PostgresManufacturingSupplyPlanRepository
from tests.test_postgres_manufacturing_execution import _actually_blocked
from tests.test_postgres_manufacturing_supply_plan import (
    SCOPE,
    baseline_manufacturing_v2_database,
    baseline_receipt_database,
    original_manufacturing_database,
    owner_phase,
    planning_runtime,
    supply_database,
)

_ = (baseline_manufacturing_v2_database, baseline_receipt_database, original_manufacturing_database, supply_database)


def original_fractional_plan(supply_database: tuple[str, str]) -> dict[str, Any]:
    system, original = planning_runtime(supply_database)
    with system.actor("maker") as (connection, _, actor):
        bom = PostgresManufacturingExecutionRepository(connection, system.tenant).prepare_bom(
            BomPreparation(number="FRACTIONAL-KG", version=1, output_item_code="PRODUCT", output_quantity="10",
                components=[{"item_code": "MATERIAL", "quantity": "0.001"}], reason="Original exact milligram demand",
                **SCOPE), command_id="fractional-bom-create", actor=actor)
    with system.actor("checker") as (connection, _, actor):
        bom = PostgresManufacturingExecutionRepository(connection, system.tenant).approve_bom(bom["id"],
            expected_digest=bom["source_digest"], command_id="fractional-bom-approve", reason="Independent base KG recipe", actor=actor)
    with system.actor("maker") as (connection, _, actor):
        center = connection.execute("SELECT id FROM reconforge.manufacturing_execution_v2_definitions WHERE tenant_id=%s AND kind='Workcenter' AND phase=1",
                                    (system.tenant,)).fetchone()["id"]
        routing = PostgresManufacturingExecutionV2Repository(connection, system.tenant).create_routing(
            RoutingPreparation("FRACTIONAL-ROUTE", 1, bom["id"], "2026-10-01", "2026-10-31",
                [{"sequence": 1, "workcenter_id": center, "name": "Original milligram operation", "minutes_per_batch": 1}],
                SCOPE, "Original approved fractional BOM routing"), command_id="fractional-route-create", actor=actor)
    routing = owner_phase(system, routing, "approve", "definition")
    request = replace(original, material=replace(original.material, number="FRACTIONAL-SUPPLY", bom_version_id=bom["id"]),
                      routing_id=routing["id"], unit_price_ceilings_minor={"MATERIAL": 3000})
    with system.actor("maker") as (connection, _, actor):
        created = PostgresManufacturingSupplyPlanRepository(connection, system.tenant).create(request, command_id="fractional-plan-create", actor=actor)
    with system.actor("checker") as (connection, _, actor):
        approved = PostgresManufacturingSupplyPlanRepository(connection, system.tenant).approve(created["source"]["id"],
            expected_digest=created["source"]["source_digest"], command_id="fractional-plan-approve", reason="Actual zero-stock milligram shortage", actor=actor)
    source = approved["source"]
    assert source["ceiling_minor"] == 3 and source["unit_price_ceilings_minor"] == {"MATERIAL": 3000}
    assert source["requirements"][0]["required_quantity_scaled"] == 1
    return {"system": system, "request": request, "created": created, "approved": approved, "source": source}


@pytest.fixture(scope="module")
def fractional_plan(supply_database: tuple[str, str]) -> dict[str, Any]:
    return original_fractional_plan(supply_database)


@pytest.fixture(scope="module")
def fractional_supply(supply_database: tuple[str, str]) -> dict[str, Any]:
    result = original_fractional_plan(supply_database)
    system, request, source = (result[key] for key in ("system", "request", "source"))
    demand = RequisitionPreparation(budget_id=request.budget_id, reason="Exact original milligram requisition",
        order=MultilineProcurementPreparation(number="SRC5-MSP-9876543210ABCDEF", supplier_code="SUP", currency_code="USD",
            posting_date="2026-10-04", period_id="period", journal_code="STOCK", ap_account_code="AP", cash_account_code="CASH",
            organization_code="ORG", entity_code="ENTITY", workspace="work", lines=(ProcurementOrderLine(item_code="MATERIAL",
                quantity="0.001", unit_price_minor=3000, location_code="MAIN/STOCK", policy_code="FIFO"),)))
    with system.actor("maker") as (connection, _, actor):
        outcome = PostgresManufacturingSupplyPlanRepository(connection, system.tenant).create_requisition(source["id"], demand,
            requirement_ids=(source["planned_requirements"][0]["id"],), expected_digest=source["source_digest"],
            command_id="fractional-pr-create", actor=actor)
    native = outcome["native_response"]
    with system.actor("checker") as (connection, _, actor):
        outcome = PostgresManufacturingSupplyPlanRepository(connection, system.tenant).act_requisition(source["id"], native["id"], "open-rfq",
            expected_version=native["row_version"], command_id="fractional-rfq", reason="Independent actual supplier request", actor=actor)
    native = outcome["native_response"]
    quotation = SupplierQuotationPreparation(supplier_code="SUP", unit_prices_minor=(5000,), valid_until="2026-10-31",
                                              reason="Original fifty dollar unit quotation for one milligram")
    quote_arguments = {"expected_version": native["row_version"], "command_id": "fractional-quote", "reason": quotation.reason, "quotation": quotation}
    with system.actor("maker") as (connection, _, actor):
        owner = PostgresManufacturingSupplyPlanRepository(connection, system.tenant)
        quoted = owner.act_requisition(source["id"], native["id"], "quote", **quote_arguments, actor=actor)
        detail = owner.get_requisition(source["id"], native["id"], actor=actor)
        assert detail["quotations"][0]["payload"]["total_minor"] == "5"
        assert detail["quotations"][0]["payload"]["quotation"]["unit_prices_minor"] == ["5000"]
    import os

    if directory := os.environ.get("RECONFORGE_MSP_AUTHORITY_PROOF_DIR"):
        path = Path(directory) / "fractional-quote-originals.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8") as target:
            target.write(canonical_json(supply_originals(system)) + "\n")
    return {**result, "requisition": native["id"], "quote_arguments": quote_arguments, "quoted": quoted}


def supply_originals(system: Any) -> dict[str, Any]:
    from psycopg import sql

    with system.actor("maker") as (connection, _, _):
        return {name: [row["payload"] for row in connection.execute(sql.SQL(
            "SELECT to_jsonb(t) payload FROM reconforge.{} t WHERE tenant_id=%s ORDER BY to_jsonb(t)::text").format(sql.Identifier(name)), (system.tenant,))]
            for name in supply_originals_tables()}


def current_ceiling(monkeypatch: pytest.MonkeyPatch, permission: str, maximum: str) -> list[Decimal]:
    import reconforge.infrastructure.postgres_operational_finance as core

    observed: list[Decimal] = []
    def bounded(principal: Any, **context: Any) -> Any:
        if context["required_permission"] == permission and context.get("amount") is not None:
            observed.append(context["amount"])
            return evaluate_principal_access(principal, maximum_amount=Decimal(maximum), **context)
        return evaluate_principal_access(principal, **context)
    monkeypatch.setattr(core, "evaluate_principal_access", bounded)
    return observed


def original_read(owner: PostgresManufacturingSupplyPlanRepository, fixture: dict[str, Any], operation: str, actor: Any) -> Any:
    source = fixture["source"]
    if operation == "list":
        return owner.list_plans(SCOPE, actor=actor)
    if operation == "requirement":
        return owner.get_requirement(source["planned_requirements"][0]["id"], actor=actor)
    if operation == "requisition":
        return owner.get_requisition(source["id"], fixture["requisition"], actor=actor)
    if operation == "create-replay":
        return owner.create(fixture["request"], command_id="fractional-plan-create", actor=actor)
    if operation == "quote-replay":
        return owner.act_requisition(source["id"], fixture["requisition"], "quote", **fixture["quote_arguments"], actor=actor)
    if operation == "receipt":
        return owner.command_receipt(source["id"], "fractional-quote", fixture["quoted"], actor=actor)
    return owner.get(source["id"], actor=actor)


@pytest.mark.parametrize("operation", ["get", "list", "requirement", "create-replay"])
def test_fractional_total_cannot_disclose_original_plan_unit_ceiling(fractional_plan: dict[str, Any], monkeypatch: pytest.MonkeyPatch, operation: str) -> None:
    observed = current_ceiling(monkeypatch, "manufacturing_supply_plan.read", "20")
    system = fractional_plan["system"]
    with system.actor("maker") as (connection, _, actor), pytest.raises(FinancePostingError) as refused:
        original_read(PostgresManufacturingSupplyPlanRepository(connection, system.tenant), fractional_plan, operation, actor)
    assert "denied" in refused.value.code and max(observed) == Decimal("30.00")


@pytest.mark.parametrize("operation", ["get", "list", "requirement", "requisition", "create-replay", "quote-replay", "receipt"])
@pytest.mark.parametrize("permission", ["manufacturing_supply_plan.read", "manufacturing_execution_v2.read", "manufacturing_execution.read", "inventory.read", "finance_core.read", "budget_control.read"])
def test_fractional_quote_total_cannot_disclose_original_quote_unit_price(fractional_supply: dict[str, Any], monkeypatch: pytest.MonkeyPatch, operation: str, permission: str) -> None:
    observed = current_ceiling(monkeypatch, permission, "40")
    system = fractional_supply["system"]
    with system.actor("maker") as (connection, _, actor), pytest.raises(FinancePostingError) as refused:
        original_read(PostgresManufacturingSupplyPlanRepository(connection, system.tenant), fractional_supply, operation, actor)
    assert "denied" in refused.value.code and max(observed) == Decimal("50.00")


def test_high_cap_original_command_replay_and_receipt_remain_immutable(fractional_supply: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    observed = current_ceiling(monkeypatch, "finance_core.read", "60")
    system = fractional_supply["system"]
    before = digest_payload(supply_originals(system))
    with system.actor("maker") as (connection, _, actor):
        owner = PostgresManufacturingSupplyPlanRepository(connection, system.tenant)
        assert original_read(owner, fractional_supply, "create-replay", actor) == fractional_supply["created"]
        assert original_read(owner, fractional_supply, "quote-replay", actor) == fractional_supply["quoted"]
        receipt = original_read(owner, fractional_supply, "receipt", actor)
        assert receipt["request_json"]["request"]["native_request"]["quotation"]["unit_prices_minor"] == [5000]
    assert max(observed) == Decimal("50.00")
    assert digest_payload(supply_originals(system)) == before


def test_new_quote_response_above_read_cap_rolls_back_native_offer_and_owner_version(fractional_supply: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    from reconforge.infrastructure.postgres_payables import PostgresPayablesRepository

    system = fractional_supply["system"]
    with system.actor("maker") as (connection, _, _):
        PostgresPayablesRepository(connection, system.tenant).upsert_supplier(supplier_code="SUP2", name="Second original synthetic supplier",
            currency_code="USD", workspace="work", organization_code="ORG", entity_code="ENTITY")
    before = digest_payload(supply_originals(system))
    observed = current_ceiling(monkeypatch, "manufacturing_supply_plan.read", "55")
    with system.actor("maker") as (connection, _, actor), pytest.raises(FinancePostingError) as refused:
        owner = PostgresManufacturingSupplyPlanRepository(connection, system.tenant)
        owner.act_requisition(fractional_supply["source"]["id"], fractional_supply["requisition"], "quote",
            expected_version=fractional_supply["quoted"]["native_response"]["row_version"], command_id="refused-new-fractional-quote",
            reason="New exact unit price over current response read cap", quotation=SupplierQuotationPreparation(supplier_code="SUP2",
                unit_prices_minor=(6000,), valid_until="2026-10-31", reason="New original sixty dollar unit quote"), actor=actor)
    assert "denied" in refused.value.code and max(observed) == Decimal("60.00")
    assert digest_payload(supply_originals(system)) == before


def test_new_plan_response_above_unit_cap_creates_no_owner_or_custody(fractional_plan: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    system = fractional_plan["system"]
    before = digest_payload(supply_originals(system))
    observed = current_ceiling(monkeypatch, "manufacturing_supply_plan.read", "20")
    request = replace(fractional_plan["request"], material=replace(fractional_plan["request"].material, number="REFUSED-FRACTIONAL-SUPPLY"))
    with system.actor("maker") as (connection, _, actor), pytest.raises(FinancePostingError) as refused:
        PostgresManufacturingSupplyPlanRepository(connection, system.tenant).create(request, command_id="refused-new-fractional-plan", actor=actor)
    assert "denied" in refused.value.code and max(observed) == Decimal("30.00")
    assert digest_payload(supply_originals(system)) == before


@pytest.mark.parametrize("revoked", ["permission", "scope"])
@pytest.mark.parametrize("operation", ["get", "receipt"])
def test_waiting_read_and_original_receipt_recheck_current_authority_after_source_lock(supply_database: tuple[str, str], revoked: str, operation: str) -> None:
    from reconforge.infrastructure.postgres import PostgresTenantBoundary
    from reconforge.infrastructure.postgres_scope_authority import PostgresScopeAuthorityRepository

    fixture = original_fractional_plan(supply_database)
    system, source = fixture["system"], fixture["source"]
    before = digest_payload(supply_originals(system))
    pids: dict[str, int] = {}
    def read(operation: str) -> Any:
        with system.actor("maker") as (connection, _, actor):
            connection.execute("SET LOCAL statement_timeout='30s'")
            pids[operation] = connection.execute("SELECT pg_backend_pid() pid").fetchone()["pid"]
            owner = PostgresManufacturingSupplyPlanRepository(connection, system.tenant)
            if operation == "receipt":
                return owner.command_receipt(source["id"], "fractional-plan-create", fixture["created"], actor=actor)
            return owner.get(source["id"], actor=actor)
    with ThreadPoolExecutor(max_workers=1) as workers:
        with PostgresTenantBoundary(system.factory).transaction(system.tenant) as holder:
            holder_pid = holder.execute("SELECT pg_backend_pid() pid").fetchone()["pid"]
            holder.execute("SELECT id FROM reconforge.manufacturing_supply_plans WHERE tenant_id=%s AND id=%s FOR UPDATE", (system.tenant, source["id"]))
            attempt = workers.submit(read, operation)
            _actually_blocked(system.admin_dsn, pids, operation, holder_pid)
            with PostgresTenantBoundary(system.factory).transaction(system.tenant) as revoker:
                if revoked == "scope":
                    PostgresScopeAuthorityRepository(revoker).revoke(tenant_id=system.tenant, grant_id="me1-maker-entity",
                        actor_id="poster", reason="Withdraw original entity while source response waits")
                else:
                    revoker.execute("""UPDATE reconforge.identity_role_permissions SET active=FALSE,lifecycle_version=lifecycle_version+1,
                        revoked_at=now(),revoked_by='poster',revocation_reason_code='access_change'
                        WHERE tenant_id=%s AND permission_name='finance_core.read'""", (system.tenant,))
        with pytest.raises(FinancePostingError) as refused:
            attempt.result(timeout=35)
        assert "denied" in refused.value.code
    # Scope/role lifecycle mutations are distinct from the immutable business originals.
    import psycopg
    from psycopg import sql

    with psycopg.connect(system.admin_dsn) as audit:
        originals = {name: [row[0] for row in audit.execute(sql.SQL(
            "SELECT to_jsonb(t) FROM reconforge.{} t WHERE tenant_id=%s ORDER BY to_jsonb(t)::text").format(sql.Identifier(name)), (system.tenant,))]
            for name in supply_originals_tables()}
    assert digest_payload(originals) == before


def supply_originals_tables() -> tuple[str, ...]:
    return ("manufacturing_execution_boms", "manufacturing_execution_commands", "manufacturing_execution_events",
        "manufacturing_execution_v2_definitions", "manufacturing_execution_v2_commands", "manufacturing_execution_v2_events",
        "inventory_items", "inventory_units_of_measure", "currencies",
        "manufacturing_supply_plans", "manufacturing_supply_requirements", "manufacturing_supply_stock_claims",
        "manufacturing_supply_stock_releases", "manufacturing_supply_procurement_claims", "manufacturing_supply_events", "manufacturing_supply_commands",
        "procurement_sourcing_requisitions", "procurement_sourcing_quotes", "procurement_sourcing_events", "procurement_sourcing_commands",
        "inventory_quantity_claim_gates", "inventory_quantity_source_guards", "inventory_quantity_source_releases", "finance_posting_effects")
