"""Actual nonowner ME1 commands; mandatory fixture runner never skips this file."""
from __future__ import annotations

from collections.abc import Iterator
from fractions import Fraction
from typing import Any

import pytest

from reconforge.domain.finance_posting import FinancePostingError, digest_payload
from reconforge.domain.inventory_receipt_posting import ReceiptPreparation
from reconforge.domain.manufacturing_execution import PERMISSIONS, BomPreparation, OrderPreparation
from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_finance_core import PostgresFinanceCoreRepository
from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository
from reconforge.infrastructure.postgres_inventory_core import PostgresInventoryCoreRepository
from reconforge.infrastructure.postgres_inventory_valuation import PostgresInventoryValuationRepository
from reconforge.infrastructure.postgres_manufacturing_execution import PostgresManufacturingExecutionRepository
from reconforge.infrastructure.postgres_manufacturing_execution_schema import (
    DOWNGRADE_SQL,
    UPGRADE_SQL,
    install_postgres_manufacturing_execution_schema,
)
from tests.test_postgres_inventory_receipt_posting import (
    ReceiptRuntime,
    create_receipt_runtime,
)
from tests.test_postgres_inventory_receipt_posting import (
    receipt_database as baseline_receipt_database,
)

_ = baseline_receipt_database


@pytest.fixture(scope="module")
def manufacturing_database(baseline_receipt_database: tuple[str, str]) -> Iterator[tuple[str, str]]:
    import psycopg
    from psycopg import sql
    admin_dsn, app_dsn = baseline_receipt_database
    with psycopg.connect(admin_dsn) as admin:
        install_postgres_manufacturing_execution_schema(admin)
        user = psycopg.conninfo.conninfo_to_dict(app_dsn)["user"]
        admin.execute(sql.SQL("GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA reconforge TO {}").format(sql.Identifier(user)))
    yield admin_dsn, app_dsn


def runtime(database: tuple[str, str], *, stock: bool = True) -> ReceiptRuntime:
    result = create_receipt_runtime(database)
    # Synthetic canonical master seeding uses the same broad fixture scope as the original IRP runtime.
    with PostgresTenantBoundary(result.factory).transaction(result.tenant) as connection:
        identity = PostgresIdentityRepository(connection)
        for permission in sorted(set().union(*PERMISSIONS.values()) | {"inventory.manage", "inventory.post"}):
            identity.create_permission(tenant_id=result.tenant, permission_name=permission)
            identity.grant_permission(tenant_id=result.tenant, role_name="receipt-operator", permission_name=permission)
        finance = PostgresFinanceCoreRepository(connection, result.tenant)
        for code, kind in (("WIP", "Asset"), ("FG", "Asset"), ("SCRAP", "Expense")):
            finance.upsert_account(account_code=code, name=code, account_type=kind, chart_code="DEFAULT", workspace="work")
        inventory = PostgresInventoryCoreRepository(connection, result.tenant)
        inventory.upsert_uom(uom_code="KG", name="Kilogram", decimal_places=3, workspace="work")
        inventory.upsert_item(item_code="MATERIAL", name="Exact mass input", organization_code="ORG", uom_code="KG", inventory_account_code="INVENTORY", workspace="work")
        inventory.upsert_item(item_code="PRODUCT", name="Actual finished product", organization_code="ORG", uom_code="EA", inventory_account_code="FG", workspace="work")
        PostgresInventoryValuationRepository(connection, result.tenant).upsert_policy(policy_code="MFG", organization_code="ORG", entity_code="ENTITY",
            journal_code="STOCK", receipt_clearing_account_code="WIP", cogs_account_code="COGS", adjustment_account_code="ADJUSTMENT", workspace="work")
    if stock:
        for number, item, amount, qty in (("ME-SEED-A", "ITEM", 12000, "10"), ("ME-SEED-B", "MATERIAL", 3333, "20.000")):
            with result.actor("maker") as (_, receipts, actor):
                plan = receipts.prepare_receipt(ReceiptPreparation(receipt_number=number, posting_date="2026-10-02", period_id="period", item_code=item,
                    location_code="MAIN/STOCK", quantity=qty, total_value_minor=amount, policy_code="FIFO", organization_code="ORG", entity_code="ENTITY",
                    workspace="work", reason="Exact original actual materials"), command_id=number + "-prepare", actor=actor)
            with result.actor("checker") as (_, receipts, actor):
                review = receipts.review(plan["plan_id"], command_id=number + "-review", expected_plan_digest=plan["plan_digest"], reason="Independent original receipt", actor=actor)
            with result.actor("poster") as (_, receipts, actor):
                receipts.commit(plan["plan_id"], command_id=number + "-post", expected_review_digest=review["review_digest"], reason="Actual native FIFO backing", actor=actor)
    return result


def approved_bom(system: ReceiptRuntime, *, number: str = "BOM-1") -> dict[str, Any]:
    with system.actor("maker") as (connection, _, actor):
        bom = PostgresManufacturingExecutionRepository(connection, system.tenant).prepare_bom(BomPreparation(number=number, version=1,
            output_item_code="PRODUCT", output_quantity="10", components=[{"item_code": "ITEM", "quantity": "2"}, {"item_code": "MATERIAL", "quantity": "3.000"}],
            workspace_id="work", organization_id="org", legal_entity_id="entity", organization_code="ORG", entity_code="ENTITY", reason="Versioned exact material recipe"),
            command_id=number + "-create", actor=actor)
    with system.actor("checker") as (connection, _, actor):
        return PostgresManufacturingExecutionRepository(connection, system.tenant).approve_bom(bom["id"], expected_digest=bom["source_digest"],
            command_id=number + "-approve", reason="Independent base-UOM recipe check", actor=actor)


def reserved_order(system: ReceiptRuntime, *, number: str = "WORK-1", bom: dict[str, Any] | None = None) -> dict[str, Any]:
    recipe = approved_bom(system, number="BOM-" + number) if bom is None else bom
    with system.actor("maker") as (connection, _, actor):
        return PostgresManufacturingExecutionRepository(connection, system.tenant).create_order(OrderPreparation(number=number, bom_version_id=recipe["id"],
            output_quantity="10", component_location_code="MAIN/STOCK", finished_location_code="MAIN/STOCK", component_policy_code="FIFO", finished_policy_code="MFG",
            journal_code="STOCK", wip_account_code="WIP", scrap_account_code="SCRAP", period_id="period", posting_date="2026-10-04", workspace_id="work",
            organization_id="org", legal_entity_id="entity", organization_code="ORG", entity_code="ENTITY", reason="Actual governed material production"),
            command_id=number + "-create", actor=actor)


def phase(system: ReceiptRuntime, source: dict[str, Any], operation: str, *, child: bool = False, name: str | None = None) -> dict[str, Any]:
    selected = name or {"prepare": "maker", "review": "checker", "post": "poster", "cancel": "checker"}[operation]
    with system.actor(selected) as (connection, _, actor):
        owner = PostgresManufacturingExecutionRepository(connection, system.tenant)
        call = owner.act_completion if child else owner.act
        return call(source["id"], operation, expected_digest=source["source_digest"], command_id=source["id"] + "-" + operation,
                    reason="Independent actual " + operation, actor=actor)


def integer_even(value: Fraction) -> int:
    base, residual = divmod(value.numerator, value.denominator)
    return base + int(residual * 2 > value.denominator or residual * 2 == value.denominator and base % 2 == 1)


def financial_oracle(system: ReceiptRuntime) -> dict[str, int]:
    with system.actor("poster") as (connection, _, _):
        rows = connection.execute("""SELECT account.account_code,sum((detail->>'debit_minor')::numeric-(detail->>'credit_minor')::numeric) balance
            FROM reconforge.finance_posting_effects effect,jsonb_array_elements(effect.snapshot_json->'lines') detail
            JOIN reconforge.finance_accounts account ON account.id=detail->>'account_id' AND account.tenant_id=%s
            WHERE effect.tenant_id=%s GROUP BY account.account_code""", (system.tenant, system.tenant)).fetchall()
        return {row["account_code"]: int(row["balance"]) for row in rows}


def complete_issue(system: ReceiptRuntime) -> dict[str, Any]:
    return phase(system, phase(system, phase(system, reserved_order(system), "prepare"), "review"), "post")


def completion(system: ReceiptRuntime, order: dict[str, Any], command: str = "partial-create") -> dict[str, Any]:
    with system.actor("maker") as (connection, _, actor):
        return PostgresManufacturingExecutionRepository(connection, system.tenant).prepare_completion(order["id"], good_quantity="3",
            scrap_quantity="1", period_id="period", posting_date="2026-10-05", command_id=command,
            reason="Partial good output and explicit abnormal loss", actor=actor)


def retained_digest(system: ReceiptRuntime) -> str:
    from psycopg import sql

    from tests.test_postgres_inventory_receipt_posting import backing_digest
    with system.actor("poster") as (connection, _, _):
        parts = {name: [row["payload"] for row in connection.execute(sql.SQL("SELECT to_jsonb(t) payload FROM reconforge.{} t WHERE tenant_id=%s ORDER BY to_jsonb(t)::text").format(sql.Identifier(name)), (system.tenant,)).fetchall()]
                 for name in ("manufacturing_execution_boms", "manufacturing_execution_orders", "manufacturing_execution_requirements",
                              "manufacturing_execution_reservations", "manufacturing_execution_completions", "manufacturing_execution_commands", "manufacturing_execution_events")}
        return digest_payload({"owner": parts, "native": backing_digest(connection, system.tenant)})


def test_actual_versioned_bom_component_fifo_wip_partial_fg_abnormal_scrap_and_lost_ack(manufacturing_database: tuple[str, str]) -> None:
    system = runtime(manufacturing_database)
    order = reserved_order(system)
    with system.actor("maker") as (connection, _, actor):
        requirement = PostgresManufacturingExecutionRepository(connection, system.tenant).get_requirement(order["requirements"][0]["requirement_id"], actor=actor)
        assert requirement["order_source_digest"] == order["source_digest"]
        assert requirement["required_quantity_scaled"] in {2, 3000}
    prepared = phase(system, order, "prepare")
    # The oracle knows only original receipt quantities and values, not owner allocation code.
    cost = integer_even(Fraction(12000 * 2, 10)) + integer_even(Fraction(3333 * 3000, 20000))
    assert prepared["issue_plan"]["total_cost_minor"] == cost == 2900
    reviewed = phase(system, prepared, "review")
    issued = phase(system, reviewed, "post")
    assert issued["phase"] == 3 and financial_oracle(system)["WIP"] == cost
    with system.actor("poster") as (connection, _, actor):
        replay = PostgresManufacturingExecutionRepository(connection, system.tenant).act(order["id"], "post", expected_digest=order["source_digest"],
            command_id=order["id"] + "-post", reason="Independent actual post", actor=actor)
        assert replay == issued
    for index, (good, scrap) in enumerate((("3", "1"), ("6", "0")), 1):
        with system.actor("maker") as (connection, _, actor):
            completion = PostgresManufacturingExecutionRepository(connection, system.tenant).prepare_completion(order["id"], good_quantity=good,
                scrap_quantity=scrap, period_id="period", posting_date="2026-10-05", command_id=f"completion-{index}", reason="Partial good output and explicit abnormal loss", actor=actor)
        reviewed_completion = phase(system, completion, "review", child=True)
        posted = phase(system, reviewed_completion, "post", child=True)
        assert posted["phase"] == 2
    with system.actor("poster") as (connection, _, actor):
        final = PostgresManufacturingExecutionRepository(connection, system.tenant).get_order(order["id"], actor=actor)
        assert (final["phase"], final["disposed_quantity_scaled"], final["released_cost_minor"], final["wip_minor"]) == (4, 10, 2900, 0)
        output = connection.execute("SELECT sum(original_quantity_scaled) quantity,sum(original_value_minor) value FROM reconforge.inventory_cost_layers WHERE tenant_id=%s AND item_id=%s", (system.tenant, order["output_item_id"])).fetchone()
        assert (int(output["quantity"]), int(output["value"])) == (9, 2610)
        assert connection.execute("SELECT count(*) count FROM reconforge.inventory_layer_consumptions WHERE tenant_id=%s", (system.tenant,)).fetchone()["count"] == 2
    totals = financial_oracle(system)
    assert (totals["WIP"], totals["FG"], totals["SCRAP"], totals["INVENTORY"]) == (0, 2610, 290, 15333 - 2900)
    assert sum(totals.values()) == 0


def test_cancel_releases_whole_material_claim_and_preserves_prior_ack(manufacturing_database: tuple[str, str]) -> None:
    system = runtime(manufacturing_database)
    first = reserved_order(system)
    prepared = phase(system, first, "prepare")
    reviewed = phase(system, prepared, "review")
    cancelled = phase(system, reviewed, "cancel")
    assert cancelled["phase"] == 5
    with system.actor("maker") as (connection, _, actor):
        replay = PostgresManufacturingExecutionRepository(connection, system.tenant).act(first["id"], "prepare", expected_digest=first["source_digest"],
            command_id=first["id"] + "-prepare", reason="Independent actual prepare", actor=actor)
        assert replay == prepared
        assert connection.execute("SELECT count(*) count FROM reconforge.manufacturing_execution_reservations WHERE tenant_id=%s AND order_id=%s AND state='Released'", (system.tenant, first["id"])).fetchone()["count"] == 2
    second = reserved_order(system, number="WORK-2")
    assert phase(system, second, "prepare")["issue_plan"]["total_cost_minor"] == 2900


def test_direct_sql_cannot_post_source_phase_without_native_financial_inverse_or_commands(manufacturing_database: tuple[str, str]) -> None:
    import psycopg
    system = runtime(manufacturing_database)
    source = reserved_order(system)
    with pytest.raises(psycopg.errors.CheckViolation), system.actor("poster") as (connection, _, actor):
        connection.execute("SELECT set_config('app.manufacturing_execution_actor_id',%s,true)", (actor.user_id,))
        connection.execute("UPDATE reconforge.manufacturing_execution_orders SET phase=3 WHERE tenant_id=%s AND id=%s", (system.tenant, source["id"]))
    with system.actor("poster") as (connection, _, actor):
        assert PostgresManufacturingExecutionRepository(connection, system.tenant).get_order(source["id"], actor=actor)["phase"] == 0
    assert financial_oracle(system).get("WIP", 0) == 0


def test_populated_downgrade_refusal_retains_native_claim(manufacturing_database: tuple[str, str]) -> None:
    import psycopg
    # This module fixture is already populated by other cases: every retained source blocks rollback atomically.
    system = runtime(manufacturing_database)
    source = reserved_order(system)
    with pytest.raises(psycopg.errors.CheckViolation), psycopg.connect(system.admin_dsn) as admin:
        admin.execute(DOWNGRADE_SQL)
    with system.actor("maker") as (connection, _, actor):
        assert PostgresManufacturingExecutionRepository(connection, system.tenant).get_order(source["id"], actor=actor)["source_digest"] == source["source_digest"]
        assert connection.execute("SELECT manufacturing_claim_state FROM reconforge.inventory_movements WHERE tenant_id=%s AND id=%s", (system.tenant, source["movement_id"])).fetchone()["manufacturing_claim_state"] == "Reserved"
    assert "RENAME TO stock_sales_capacity_pre_me1" in UPGRADE_SQL


def test_cancel_reviewed_completion_retains_receipt_draft_and_exact_ack_but_no_effect(manufacturing_database: tuple[str, str]) -> None:
    system = runtime(manufacturing_database)
    order = complete_issue(system)
    prepared = completion(system, order)
    reviewed = phase(system, prepared, "review", child=True)
    cancelled = phase(system, reviewed, "cancel", child=True)
    assert cancelled["phase"] == 3 and cancelled["receipt_effect"] is None and cancelled["scrap_effect_id"] is None
    with system.actor("maker") as (connection, receipts, actor):
        owner = PostgresManufacturingExecutionRepository(connection, system.tenant)
        assert owner.prepare_completion(order["id"], good_quantity="3", scrap_quantity="1", period_id="period", posting_date="2026-10-05",
            command_id="partial-create", reason="Partial good output and explicit abnormal loss", actor=actor) == prepared
        with pytest.raises(FinancePostingError, match="manufacturing"):
            receipts.get_plan(prepared["receipt_plan"]["plan_id"], actor=actor)
        assert connection.execute("SELECT status FROM reconforge.finance_entries WHERE tenant_id=%s AND id=%s", (system.tenant, prepared["scrap_entry"]["entry_id"])).fetchone()["status"] == "Voided"
        assert connection.execute("SELECT count(*) count FROM reconforge.inventory_receipt_links WHERE tenant_id=%s AND plan_id=%s", (system.tenant, prepared["receipt_plan"]["plan_id"])).fetchone()["count"] == 0
        live = owner.get_order(order["id"], actor=actor)
        assert (live["wip_minor"], live["disposed_quantity_scaled"], live["released_cost_minor"]) == (2900, 0, 0)
    assert phase(system, prepared, "review", child=True) == reviewed
    with pytest.raises(FinancePostingError, match="phase"):
        phase(system, cancelled, "post", child=True)
    replacement = completion(system, order, "replacement-create")
    assert replacement["id"] != prepared["id"]
    assert financial_oracle(system)["WIP"] == 2900


def test_forged_historical_response_refused_by_sql_and_source_transaction_rollback(manufacturing_database: tuple[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    system = runtime(manufacturing_database)
    before = retained_digest(system)
    original = PostgresManufacturingExecutionRepository._remember

    def forge(owner: Any, source: Any, *args: Any, **kwargs: Any) -> Any:
        return original(owner, {**source, "components": []}, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(PostgresManufacturingExecutionRepository, "_remember", forge)
        with pytest.raises(FinancePostingError, match="retained financial"):
            approved_bom(system)
    assert retained_digest(system) == before
    assert approved_bom(system)["phase"] == 1


def test_late_scrap_failure_rolls_back_actual_finished_receipt_and_both_native_effects(manufacturing_database: tuple[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    system = runtime(manufacturing_database)
    source = phase(system, completion(system, complete_issue(system)), "review", child=True)
    before = retained_digest(system)
    with system.actor("poster") as (connection, _, actor):
        owner = PostgresManufacturingExecutionRepository(connection, system.tenant)
        original = owner._post_entry

        def fail_after_native_post(*args: Any, **kwargs: Any) -> Any:
            original(*args, **kwargs)
            raise RuntimeError("synthetic late actual scrap failure")

        with monkeypatch.context() as patch:
            patch.setattr(owner, "_post_entry", fail_after_native_post)
            with pytest.raises(RuntimeError, match="late actual scrap"):
                owner.act_completion(source["id"], "post", expected_digest=source["source_digest"], command_id=source["id"] + "-post", reason="Independent actual post", actor=actor)
    assert retained_digest(system) == before
    assert phase(system, source, "post", child=True)["phase"] == 2
    assert financial_oracle(system)["WIP"] == 1740


def test_bounded_same_date_native_receipt_search_exhaustion_is_atomic(manufacturing_database: tuple[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    import reconforge.infrastructure.postgres_manufacturing_execution as module
    system = runtime(manufacturing_database)
    order = complete_issue(system)
    posted = phase(system, phase(system, completion(system, order), "review", child=True), "post", child=True)
    assert 1 <= posted["receipt_identity_candidates"] <= 4096
    before = retained_digest(system)
    attempts = 0

    def lowest_identity(plan: str, tag: str) -> str:
        nonlocal attempts
        attempts += 1
        return "IRP1-MOV-" + "0" * 32

    with monkeypatch.context() as patch:
        patch.setattr(module, "artifact_id", lowest_identity)
        with pytest.raises(FinancePostingError, match="exhausted bounded"):
            completion(system, order, "same-date-rejected")
    assert attempts == 4096 and retained_digest(system) == before
