"""Actual nonowner ME2 stock/WIP, original expense claims and quality disposition."""
from collections.abc import Iterator
from fractions import Fraction
from typing import Any

import pytest

from reconforge.domain.manufacturing_execution import OrderPreparation
from reconforge.domain.manufacturing_execution_v2 import (
    PERMISSIONS,
    ManufacturingOrderPreparation,
    RoutingPreparation,
    WorkcenterPreparation,
)
from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_finance_core import PostgresFinanceCoreRepository
from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository
from reconforge.infrastructure.postgres_manufacturing_execution_v2 import PostgresManufacturingExecutionV2Repository
from reconforge.infrastructure.postgres_manufacturing_execution_v2_schema import (
    install_postgres_manufacturing_execution_v2_schema,
)
from tests.test_postgres_manufacturing_execution import (
    approved_bom,
    baseline_receipt_database,
    financial_oracle,
    runtime,
)
from tests.test_postgres_manufacturing_execution import manufacturing_database as original_manufacturing_database

_ = (original_manufacturing_database, baseline_receipt_database)
SCOPE = {"workspace_id": "work", "organization_id": "org", "legal_entity_id": "entity", "organization_code": "ORG", "entity_code": "ENTITY"}


@pytest.fixture(scope="module")
def manufacturing_v2_database(original_manufacturing_database: tuple[str, str]) -> Iterator[tuple[str, str]]:
    import psycopg
    from psycopg import sql
    admin_dsn, app_dsn = original_manufacturing_database
    with psycopg.connect(admin_dsn) as connection:
        install_postgres_manufacturing_execution_v2_schema(connection)
        role = psycopg.conninfo.conninfo_to_dict(app_dsn)["user"]
        connection.execute(sql.SQL("GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA reconforge TO {}").format(sql.Identifier(role)))
    yield admin_dsn, app_dsn


def system(database: tuple[str, str]) -> Any:
    result = runtime(database)
    with PostgresTenantBoundary(result.factory).transaction(result.tenant) as connection:
        identity = PostgresIdentityRepository(connection)
        for permission in sorted(set().union(*PERMISSIONS.values())):
            identity.create_permission(tenant_id=result.tenant, permission_name=permission)
            identity.grant_permission(tenant_id=result.tenant, role_name="receipt-operator", permission_name=permission)
        finance = PostgresFinanceCoreRepository(connection, result.tenant)
        for code, kind in (("LABOR", "Expense"), ("OVERHEAD", "Expense"), ("ACCRUAL", "Liability")):
            finance.upsert_account(account_code=code, name=code, account_type=kind, chart_code="DEFAULT", workspace="work")
    return result


def original_expense(result: Any, account: str, number: str, amount: str) -> tuple[str, str]:
    with result.actor("maker") as (_, receipts, actor):
        draft = receipts.finance.finance.create_entry(entry_number=number, organization_code="ORG", entity_code="ENTITY",
            period_id="period", journal_code="STOCK", posting_date="2026-10-03", workspace="work", description="Original actual expense",
            actor_label=actor.username, lines=[{"account_code": account, "debit": amount}, {"account_code": "ACCRUAL", "credit": amount}])
    with result.actor("checker") as (_, receipts, actor):
        receipts.finance.finance.validate_entry(draft["id"], reason="Independent original expense", actor_label=actor.username)
        reviewed = receipts.finance.preview(draft["id"], actor=actor)
    with result.actor("poster") as (_, receipts, actor):
        effect = receipts.finance.post(draft["id"], command_id=number + "-post", expected_validation_digest=reviewed["validation_digest"], reason="Actual expense source", actor=actor)
        original = receipts.connection.execute("SELECT id FROM reconforge.finance_entry_lines WHERE tenant_id=%s AND entry_id=%s AND debit_minor>0",
            (result.tenant, draft["id"])).fetchone()
        return effect["id"], original["id"]


def owner_phase(result: Any, source: dict[str, Any], operation: str, kind: str = "order") -> dict[str, Any]:
    person = {"prepare": "maker", "approve": "checker", "review": "checker", "post": "poster", "cancel": "checker"}[operation]
    with result.actor(person) as (connection, _, actor):
        owner = PostgresManufacturingExecutionV2Repository(connection, result.tenant)
        method = {"order": owner.act_order, "production": owner.act_production, "inspection": owner.act_inspection, "definition": owner.approve_definition}[kind]
        parameters = {"expected_digest": source["source_digest"], "command_id": source["id"] + "-" + operation,
                      "reason": "Independent actual " + operation, "actor": actor}
        return method(source["id"], **parameters) if kind == "definition" else method(source["id"], operation, **parameters)


def order(result: Any) -> dict[str, Any]:
    bom = approved_bom(result)
    with result.actor("maker") as (connection, _, actor):
        center = PostgresManufacturingExecutionV2Repository(connection, result.tenant).create_workcenter(
            WorkcenterPreparation("ASSEMBLY", 1, "Actual assembly and inspection", "2026-10-01", "2026-10-31", SCOPE, "Synthetic approved workcenter"), command_id="wc-create", actor=actor)
    center = owner_phase(result, center, "approve", "definition")
    with result.actor("maker") as (connection, _, actor):
        route = PostgresManufacturingExecutionV2Repository(connection, result.tenant).create_routing(
            RoutingPreparation("PRODUCT-ROUTE", 1, bom["id"], "2026-10-01", "2026-10-31",
                [{"sequence": 1, "workcenter_id": center["id"], "name": "Assembly and functional check", "minutes_per_batch": 60}], SCOPE,
                "Actual effective original engineering sequence"), command_id="routing-create", actor=actor)
    route = owner_phase(result, route, "approve", "definition")
    labor, labor_line = original_expense(result, "LABOR", "LABOR-SOURCE", "20.00")
    overhead, overhead_line = original_expense(result, "OVERHEAD", "OH-SOURCE", "10.00")
    material = OrderPreparation(number="ME2-WORK", bom_version_id=bom["id"], output_quantity="10", component_location_code="MAIN/STOCK",
        finished_location_code="MAIN/STOCK", component_policy_code="FIFO", finished_policy_code="MFG", journal_code="STOCK", wip_account_code="WIP",
        scrap_account_code="SCRAP", period_id="period", posting_date="2026-10-04", **SCOPE, reason="Expense-backed inspected actual production")
    claims = [{"effect_id": labor, "line_id": labor_line, "kind": "Labor", "operation_sequence": 1, "minutes": 60, "rate_minor_per_hour": 600},
              {"effect_id": overhead, "line_id": overhead_line, "kind": "Overhead", "operation_sequence": 1, "minutes": 30, "rate_minor_per_hour": 600}]
    with result.actor("maker") as (connection, _, actor):
        return PostgresManufacturingExecutionV2Repository(connection, result.tenant).create_order(
            ManufacturingOrderPreparation(material, route["id"], claims), command_id="me2-create", actor=actor)


def half_even(value: Fraction) -> int:
    whole, residual = divmod(value.numerator, value.denominator)
    return whole + int(residual * 2 > value.denominator or residual * 2 == value.denominator and whole % 2)


def test_original_expense_backed_material_wip_quality_hold_then_actual_saleable_fg_and_abnormal_loss(manufacturing_v2_database: tuple[str, str]) -> None:
    result = system(manufacturing_v2_database)
    source = order(result)
    posted = owner_phase(result, owner_phase(result, owner_phase(result, source, "prepare"), "review"), "post")
    total = half_even(Fraction(12000 * 2, 10)) + half_even(Fraction(3333 * 3000, 20000)) + 600 + 300
    assert posted["total_cost_minor"] == total == 3800
    assert financial_oracle(result)["WIP"] == 3800
    for index, (produced, accepted, rejected) in enumerate((("4", "3", "1"), ("6", "6", "0")), 1):
        with result.actor("maker") as (connection, _, actor):
            held = PostgresManufacturingExecutionV2Repository(connection, result.tenant).produce(source["id"], output_quantity=produced,
                operations=[{"sequence": 1, "minutes": 24 if index == 1 else 36, "evidence_reference": "SYN-RUN-" + str(index)}],
                period_id="period", posting_date=f"2026-10-0{4 + index}", command_id=f"produce-{index}", reason="Actual partial production awaiting inspection", actor=actor)
        held = owner_phase(result, owner_phase(result, held, "review", "production"), "post", "production")
        with result.actor("poster") as (connection, _, actor):
            view = PostgresManufacturingExecutionV2Repository(connection, result.tenant).get_order(source["id"], actor=actor)
            assert view["held_quantity_scaled"] == int(produced)
            # A posted quality hold creates zero native FG stock, even with real material/expense WIP.
            quantity = connection.execute("SELECT COALESCE(sum(original_quantity_scaled),0) qty FROM reconforge.inventory_cost_layers WHERE tenant_id=%s AND item_id=%s",
                (result.tenant, view["material"]["output_item_id"])).fetchone()["qty"]
            assert int(quantity) == (0 if index == 1 else 3)
        with result.actor("maker") as (connection, _, actor):
            inspection = PostgresManufacturingExecutionV2Repository(connection, result.tenant).inspect(held["id"], accepted_quantity=accepted,
                rejected_quantity=rejected, inspection_reference=f"SYN-QC-{index}", period_id="period", posting_date=f"2026-10-0{4 + index}",
                command_id=f"inspect-{index}", reason="Complete independent held tranche acceptance and rejection", actor=actor)
        inspection = owner_phase(result, owner_phase(result, inspection, "review", "inspection"), "post", "inspection")
        assert inspection["phase"] == 2
    with result.actor("poster") as (connection, _, actor):
        final = PostgresManufacturingExecutionV2Repository(connection, result.tenant).get_order(source["id"], actor=actor)
        assert (final["phase"], final["wip_minor"], final["held_quantity_scaled"]) == (4, 0, 0)
        assert final["material"]["execution_version"] == 2 and final["material"]["wip_minor"] == 0
    balances = financial_oracle(result)
    assert (balances["FG"], balances["SCRAP"], balances["WIP"], balances["LABOR"], balances["OVERHEAD"]) == (3420, 380, 0, 1400, 700)
