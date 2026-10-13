"""Actual pre-stock engineering planning and native exclusive quantity custody."""
from collections.abc import Iterator
from typing import Any

import pytest

from reconforge.domain.budget_control import BudgetDefinition, BudgetScope
from reconforge.domain.inventory_receipt_posting import ReceiptPreparation
from reconforge.domain.manufacturing_execution import OrderPreparation
from reconforge.domain.manufacturing_execution_v2 import PERMISSIONS as EXECUTION_PERMISSIONS
from reconforge.domain.manufacturing_execution_v2 import RoutingPreparation, WorkcenterPreparation
from reconforge.domain.manufacturing_supply_plan import PERMISSIONS, SupplyPlanPreparation
from reconforge.domain.procurement_partial import (
    MultilineProcurementPreparation,
    ProcurementOrderLine,
    ProcurementPartialError,
)
from reconforge.domain.procurement_sourcing import PERMISSIONS as SOURCING_PERMISSIONS
from reconforge.domain.procurement_sourcing import RequisitionPreparation, SupplierQuotationPreparation
from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_budget_control import PostgresBudgetControlRepository
from reconforge.infrastructure.postgres_finance_core import PostgresFinanceCoreRepository
from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository
from reconforge.infrastructure.postgres_inventory_core import PostgresInventoryCoreRepository
from reconforge.infrastructure.postgres_manufacturing_execution_v2 import PostgresManufacturingExecutionV2Repository
from reconforge.infrastructure.postgres_manufacturing_supply_plan import PostgresManufacturingSupplyPlanRepository
from reconforge.infrastructure.postgres_manufacturing_supply_plan_schema import (
    install_postgres_manufacturing_supply_plan_schema,
)
from reconforge.infrastructure.postgres_payables import PostgresPayablesRepository
from reconforge.infrastructure.postgres_procurement_sourcing import PostgresProcurementSourcingRepository
from tests.test_postgres_manufacturing_execution import approved_bom, runtime
from tests.test_postgres_manufacturing_execution_v2 import (
    baseline_receipt_database,
    original_manufacturing_database,
    owner_phase,
)
from tests.test_postgres_manufacturing_execution_v2 import (
    manufacturing_v2_database as baseline_manufacturing_v2_database,
)

_ = (baseline_receipt_database, original_manufacturing_database, baseline_manufacturing_v2_database)
SCOPE = {"workspace_id": "work", "organization_id": "org", "legal_entity_id": "entity", "organization_code": "ORG", "entity_code": "ENTITY"}
TABLES = ("manufacturing_supply_plans", "manufacturing_supply_requirements", "manufacturing_supply_stock_claims",
          "manufacturing_supply_stock_releases", "manufacturing_supply_procurement_claims", "manufacturing_supply_events", "manufacturing_supply_commands")


@pytest.fixture(scope="module")
def supply_database(baseline_manufacturing_v2_database: tuple[str, str]) -> Iterator[tuple[str, str]]:
    import psycopg
    from psycopg import sql

    with psycopg.connect(baseline_manufacturing_v2_database[0]) as connection:
        install_postgres_manufacturing_supply_plan_schema(connection)
        role = psycopg.conninfo.conninfo_to_dict(baseline_manufacturing_v2_database[1])["user"]
        connection.execute(sql.SQL("GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA reconforge TO {}").format(sql.Identifier(role)))
    yield baseline_manufacturing_v2_database


def planning_runtime(database: tuple[str, str]) -> tuple[Any, SupplyPlanPreparation]:
    system = runtime(database, stock=False)
    with PostgresTenantBoundary(system.factory).transaction(system.tenant) as connection:
        identity = PostgresIdentityRepository(connection)
        permissions = set().union(*PERMISSIONS.values(), *EXECUTION_PERMISSIONS.values(), *SOURCING_PERMISSIONS.values())
        permissions |= {"budget_control.manage", "budget_control.approve", "payables.manage"}
        for permission in sorted(permissions):
            identity.create_permission(tenant_id=system.tenant, permission_name=permission)
            identity.grant_permission(tenant_id=system.tenant, role_name="receipt-operator", permission_name=permission)
        finance = PostgresFinanceCoreRepository(connection, system.tenant)
        for code, kind in (("AP", "Liability"), ("CASH", "Asset"), ("LABOR", "Expense"), ("OVERHEAD", "Expense"), ("ACCRUAL", "Liability")):
            finance.upsert_account(account_code=code, name=code, account_type=kind, chart_code="DEFAULT", workspace="work")
        PostgresPayablesRepository(connection, system.tenant).upsert_supplier(supplier_code="SUP", name="Actual synthetic sourcing supplier",
            currency_code="USD", workspace="work", organization_code="ORG", entity_code="ENTITY")
    bom = approved_bom(system)
    with system.actor("maker") as (connection, _, actor):
        center = PostgresManufacturingExecutionV2Repository(connection, system.tenant).create_workcenter(
            WorkcenterPreparation("PLAN-ASSEMBLY", 1, "Real planned assembly", "2026-10-01", "2026-10-31", SCOPE,
                                 "Actual demand before stock"), command_id="plan-center-create", actor=actor)
    center = owner_phase(system, center, "approve", "definition")
    with system.actor("maker") as (connection, _, actor):
        route = PostgresManufacturingExecutionV2Repository(connection, system.tenant).create_routing(
            RoutingPreparation("PLAN-ROUTE", 1, bom["id"], "2026-10-01", "2026-10-31",
                [{"sequence": 1, "workcenter_id": center["id"], "name": "Assembly and inspection", "minutes_per_batch": 60}],
                SCOPE, "Approved route for real future shortage"), command_id="plan-route-create", actor=actor)
    route = owner_phase(system, route, "approve", "definition")
    scope = BudgetScope("work", "org", "entity")
    with system.actor("maker") as (connection, _, _):
        budgets = PostgresBudgetControlRepository(connection, system.tenant)
        budget = budgets.create(scope, BudgetDefinition("SUPPLY-PLAN", "Actual planned sourcing budget", "period", "USD", 20000), command_id="plan-budget-create")
        budget = budgets.transition(scope, budget["id"], action="submit", expected_version=budget["row_version"],
                                    reason="Submit actual budget", command_id="plan-budget-submit")
    with system.actor("checker") as (connection, _, _):
        budget = PostgresBudgetControlRepository(connection, system.tenant).transition(scope, budget["id"], action="approve",
            expected_version=budget["row_version"], reason="Approve actual bounded expenditure", command_id="plan-budget-approve")
    material = OrderPreparation(number="SUPPLY-WORK", bom_version_id=bom["id"], output_quantity="10", component_location_code="MAIN/STOCK",
        finished_location_code="MAIN/STOCK", component_policy_code="FIFO", finished_policy_code="MFG", journal_code="STOCK", wip_account_code="WIP",
        scrap_account_code="SCRAP", period_id="period", posting_date="2026-10-04", **SCOPE, reason="Genuine pre-stock planned production")
    return system, SupplyPlanPreparation(material, route["id"], budget["id"], {"ITEM": 1200, "MATERIAL": 100})


def test_real_zero_stock_approved_bom_demand_then_exact_shortage_and_terminal_cancel_without_fake_movement(
        supply_database: tuple[str, str]) -> None:
    system, request = planning_runtime(supply_database)
    with system.actor("maker") as (connection, _, actor):
        owner = PostgresManufacturingSupplyPlanRepository(connection, system.tenant)
        created = owner.create(request, command_id="planned-create", actor=actor)
        assert owner.create(request, command_id="planned-create", actor=actor) == created
        assert created["source"]["phase"] == 0
    with system.actor("checker") as (connection, _, actor):
        owner = PostgresManufacturingSupplyPlanRepository(connection, system.tenant)
        approved = owner.approve(created["source"]["id"], expected_digest=created["source"]["source_digest"], command_id="planned-approve",
                                 reason="Independent exact zero-stock shortage", actor=actor)
        assert owner.approve(created["source"]["id"], expected_digest=created["source"]["source_digest"], command_id="planned-approve",
                             reason="Independent exact zero-stock shortage", actor=actor) == approved
        requirements = approved["source"]["planned_requirements"]
        assert {r["item_code"]: (r["coverage"]["onhand_reserved_scaled"], r["coverage"]["shortage_quantity_scaled"])
                for r in requirements} == {"ITEM": (0, 2), "MATERIAL": (0, 3000)}
        assert connection.execute("SELECT count(*) n FROM reconforge.inventory_movements WHERE tenant_id=%s", (system.tenant,)).fetchone()["n"] == 0
        assert connection.execute("SELECT count(*) n FROM reconforge.manufacturing_execution_orders WHERE tenant_id=%s", (system.tenant,)).fetchone()["n"] == 0
        assert connection.execute("SELECT count(*) n FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (system.tenant,)).fetchone()["n"] == 0
        cancelled = owner.cancel(created["source"]["id"], expected_digest=created["source"]["source_digest"], command_id="planned-cancel",
                                 reason="Retain original gross demand and cancel future supply", actor=actor)
        assert cancelled["source"]["phase"] == 3
        assert owner.get_requirement(requirements[0]["id"], actor=actor)["coverage"] == requirements[0]["coverage"]
    with system.actor("maker") as (connection, _, actor):
        assert PostgresManufacturingSupplyPlanRepository(connection, system.tenant).create(request, command_id="planned-create", actor=actor) == created
        assert connection.execute("SELECT count(*) n FROM reconforge.inventory_movements WHERE tenant_id=%s", (system.tenant,)).fetchone()["n"] == 0


def seed_partial_stock(system: Any) -> None:
    for number, item, amount, qty in (("PLAN-SEED-A", "ITEM", 1200, "1"), ("PLAN-SEED-B", "MATERIAL", 50, "0.500")):
        with system.actor("maker") as (_, receipts, actor):
            plan = receipts.prepare_receipt(ReceiptPreparation(receipt_number=number, posting_date="2026-10-02", period_id="period", item_code=item,
                location_code="MAIN/STOCK", quantity=qty, total_value_minor=amount, policy_code="FIFO", organization_code="ORG", entity_code="ENTITY",
                workspace="work", reason="Actual partial stock before future demand"), command_id=number + "-prepare", actor=actor)
        with system.actor("checker") as (_, receipts, actor):
            reviewed = receipts.review(plan["plan_id"], command_id=number + "-review", expected_plan_digest=plan["plan_digest"],
                                       reason="Independent native stock review", actor=actor)
        with system.actor("poster") as (_, receipts, actor):
            receipts.commit(plan["plan_id"], command_id=number + "-post", expected_review_digest=reviewed["review_digest"],
                            reason="Actual original FIFO stock", actor=actor)


def test_exclusive_partial_onhand_refuses_ordinary_posted_withdrawal_without_private_planner_select_then_cancel_releases(
        supply_database: tuple[str, str]) -> None:
    import psycopg
    from psycopg import sql

    system, request = planning_runtime(supply_database)
    seed_partial_stock(system)
    with system.actor("maker") as (connection, _, actor):
        source = PostgresManufacturingSupplyPlanRepository(connection, system.tenant).create(request, command_id="partial-create", actor=actor)["source"]
    with system.actor("checker") as (connection, _, actor):
        owner = PostgresManufacturingSupplyPlanRepository(connection, system.tenant)
        approved = owner.approve(source["id"], expected_digest=source["source_digest"], command_id="partial-approve",
                                 reason="Exclusive real onhand and shortage", actor=actor)["source"]
        assert {row["item_code"]: (row["coverage"]["onhand_reserved_scaled"], row["coverage"]["shortage_quantity_scaled"])
                for row in approved["planned_requirements"]} == {"ITEM": (1, 1), "MATERIAL": (500, 2500)}
        assert len(approved["stock_claims"]) == 2
        gates = [dict(row) for row in connection.execute("SELECT item_id,pool_kind,location_id,version FROM reconforge.inventory_quantity_claim_gates WHERE tenant_id=%s ORDER BY item_id,pool_kind,location_id",
                                                       (system.tenant,))]
        assert owner.get(source["id"], actor=actor) == approved
        assert gates == [dict(row) for row in connection.execute("SELECT item_id,pool_kind,location_id,version FROM reconforge.inventory_quantity_claim_gates WHERE tenant_id=%s ORDER BY item_id,pool_kind,location_id",
                                                              (system.tenant,))]
    with system.actor("maker") as (connection, _, actor):
        inventory = PostgresInventoryCoreRepository(connection, system.tenant)
        draft = inventory.create_movement(movement_number="ORDINARY-WITHDRAWAL", movement_type="Delivery", organization_code="ORG", entity_code="ENTITY",
            period_id="period", movement_date="2026-10-04", description="Actual ordinary stock withdrawal", source_reference="ORDINARY-WITHDRAWAL",
            workspace="work", actor_label=actor.username, lines=[{"item_code": "ITEM", "quantity": "1", "from_location": "MAIN/STOCK"}])
        movement_id = draft["id"]
    role = psycopg.conninfo.conninfo_to_dict(supply_database[1])["user"]
    try:
        with psycopg.connect(supply_database[0]) as admin:
            for table in TABLES:
                admin.execute(sql.SQL("REVOKE SELECT ON reconforge.{} FROM {}").format(sql.Identifier(table), sql.Identifier(role)))
        with system.actor("poster") as (connection, _, actor):
            with pytest.raises(psycopg.errors.CheckViolation, match="exclusive planning"), connection.transaction():
                PostgresInventoryCoreRepository(connection, system.tenant).post_movement(movement_id, reason="Direct ordinary withdrawal must respect custody", actor_label=actor.username)
                connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
            assert connection.execute("SELECT status FROM reconforge.inventory_movements WHERE tenant_id=%s AND id=%s", (system.tenant, movement_id)).fetchone()["status"] == "Draft"
            assert tuple(connection.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()) == (False, False)
    finally:
        with psycopg.connect(supply_database[0]) as admin:
            for table in TABLES:
                admin.execute(sql.SQL("GRANT SELECT ON reconforge.{} TO {}").format(sql.Identifier(table), sql.Identifier(role)))
    with system.actor("checker") as (connection, _, actor):
        cancelled = PostgresManufacturingSupplyPlanRepository(connection, system.tenant).cancel(source["id"], expected_digest=source["source_digest"],
            command_id="partial-cancel", reason="Release original exclusive inventory custody", actor=actor)
        assert all(claim["state"] == "Released" for claim in cancelled["source"]["stock_claims"])
        assert connection.execute("SELECT count(*) n FROM reconforge.inventory_quantity_source_releases WHERE tenant_id=%s", (system.tenant,)).fetchone()["n"] == 2
    with system.actor("poster") as (connection, _, actor):
        posted = PostgresInventoryCoreRepository(connection, system.tenant).post_movement(movement_id, reason="Released ordinary native stock withdrawal", actor_label=actor.username)
        assert posted["status"] == "Posted"


def test_actual_zero_stock_plan_native_src_companion_three_human_award_and_duplicate_net_shortage_refusal(supply_database: tuple[str, str]) -> None:
    from dataclasses import replace

    from reconforge.domain.finance_posting import FinancePostingError

    system, request = planning_runtime(supply_database)
    with system.actor("maker") as (connection, _, actor):
        created = PostgresManufacturingSupplyPlanRepository(connection, system.tenant).create(request, command_id="src-plan-create", actor=actor)["source"]
    with system.actor("checker") as (connection, _, actor):
        approved = PostgresManufacturingSupplyPlanRepository(connection, system.tenant).approve(created["id"], expected_digest=created["source_digest"],
            command_id="src-plan-approve", reason="Independent original net demand", actor=actor)["source"]
    demand = RequisitionPreparation(budget_id=request.budget_id, reason="Actual pre-stock shortage procurement",
        order=MultilineProcurementPreparation(number="SRC5-MSP-1234567890ABCDEF", supplier_code="SUP", currency_code="USD",
        posting_date="2026-10-04", period_id="period", journal_code="STOCK", ap_account_code="AP", cash_account_code="CASH",
        organization_code="ORG", entity_code="ENTITY", workspace="work", lines=(
            ProcurementOrderLine(item_code="ITEM", quantity="2", unit_price_minor=1200, location_code="MAIN/STOCK", policy_code="FIFO"),
            ProcurementOrderLine(item_code="MATERIAL", quantity="3.000", unit_price_minor=100, location_code="MAIN/STOCK", policy_code="FIFO"))))
    by_code = {r["item_code"]: r["id"] for r in approved["planned_requirements"]}
    with system.actor("maker") as (connection, _, actor):
        owner = PostgresManufacturingSupplyPlanRepository(connection, system.tenant)
        result = owner.create_requisition(created["id"], demand, requirement_ids=(by_code["ITEM"], by_code["MATERIAL"]),
            expected_digest=created["source_digest"], command_id="planned-pr-create", actor=actor)
        assert owner.create_requisition(created["id"], demand, requirement_ids=(by_code["ITEM"], by_code["MATERIAL"]),
            expected_digest=created["source_digest"], command_id="planned-pr-create", actor=actor) == result
        native = result["native_response"]
        assert len(result["source"]["procurement_claims"]) == 2
        with pytest.raises(FinancePostingError, match="shortage"), connection.transaction():
            owner.create_requisition(created["id"], replace(demand, order=replace(demand.order, number="SRC5-MSP-1234567890ABCDE0")),
                requirement_ids=(by_code["ITEM"], by_code["MATERIAL"]), expected_digest=created["source_digest"],
                command_id="duplicated-demand", actor=actor)
        with pytest.raises(ProcurementPartialError, match="complete active supply"), connection.transaction():
            PostgresProcurementSourcingRepository(connection, system.tenant).act(native["id"], "open-rfq", expected_version=native["row_version"],
                command_id="public-source-bypass", reason="Generic path must refuse before source locks", actor=actor)
    stages = (("open-rfq", "checker"), ("quote", "maker"), ("review-selection", "checker"), ("award", "poster"))
    for operation, person in stages:
        with system.actor(person) as (connection, _, actor):
            owner = PostgresManufacturingSupplyPlanRepository(connection, system.tenant)
            fields = {}
            if operation == "quote":
                fields["quotation"] = SupplierQuotationPreparation(supplier_code="SUP", unit_prices_minor=(1200, 100),
                    valid_until="2026-10-31", reason="Retain exact original supplier quote")
            if operation == "award":
                fields["expected_budget_version"] = PostgresBudgetControlRepository(connection, system.tenant).get(BudgetScope("work", "org", "entity"), request.budget_id)["row_version"]
            result = owner.act_requisition(created["id"], native["id"], operation, expected_version=native["row_version"],
                command_id="planned-pr-" + operation, reason="Independent actual source lifecycle", actor=actor, **fields)
            native = result["native_response"]
    with system.actor("poster") as (connection, _, actor):
        assert native["status"] == "Awarded"
        viewed = PostgresManufacturingSupplyPlanRepository(connection, system.tenant).get_requisition(created["id"], native["id"], actor=actor)
        assert viewed["head"]["status"] == "Awarded" and viewed["head"]["id"] == native["id"]
        assert len(viewed["quotations"]) == 1 and viewed["quotations"][0]["payload"]["total_minor"] == "2700"
        budget = PostgresBudgetControlRepository(connection, system.tenant).get(BudgetScope("work", "org", "entity"), request.budget_id)
        assert (budget["reserved_minor"], budget["consumed_minor"]) == ("2700", "0")
        assert connection.execute("SELECT count(*) n FROM reconforge.inventory_movements WHERE tenant_id=%s", (system.tenant,)).fetchone()["n"] == 0


def approved_partial_supply(system: Any, request: SupplyPlanPreparation) -> tuple[dict[str, Any], dict[str, Any]]:
    seed_partial_stock(system)
    with system.actor("maker") as (connection, _, actor):
        source = PostgresManufacturingSupplyPlanRepository(connection, system.tenant).create(request, command_id="cycle-plan-create", actor=actor)["source"]
    with system.actor("checker") as (connection, _, actor):
        source = PostgresManufacturingSupplyPlanRepository(connection, system.tenant).approve(source["id"], expected_digest=source["source_digest"],
            command_id="cycle-plan-approve", reason="Independent original partial-stock demand", actor=actor)["source"]
    demand = RequisitionPreparation(budget_id=request.budget_id, reason="Buy exact original unclaimed shortage",
        order=MultilineProcurementPreparation(number="SRC5-MSP-1234567890ABCDEF", supplier_code="SUP", currency_code="USD",
        posting_date="2026-10-04", period_id="period", journal_code="STOCK", ap_account_code="AP", cash_account_code="CASH",
        organization_code="ORG", entity_code="ENTITY", workspace="work", lines=(
            ProcurementOrderLine(item_code="ITEM", quantity="1", unit_price_minor=1200, location_code="MAIN/STOCK", policy_code="FIFO"),
            ProcurementOrderLine(item_code="MATERIAL", quantity="2.500", unit_price_minor=100, location_code="MAIN/STOCK", policy_code="FIFO"))))
    by_code = {row["item_code"]: row["id"] for row in source["planned_requirements"]}
    with system.actor("maker") as (connection, _, actor):
        native = PostgresManufacturingSupplyPlanRepository(connection, system.tenant).create_requisition(source["id"], demand,
            requirement_ids=(by_code["ITEM"], by_code["MATERIAL"]), expected_digest=source["source_digest"], command_id="cycle-pr-create", actor=actor)["native_response"]
    for operation, person in (("open-rfq", "checker"), ("quote", "maker"), ("review-selection", "checker"), ("award", "poster")):
        with system.actor(person) as (connection, _, actor):
            fields: dict[str, Any] = {}
            if operation == "quote":
                fields["quotation"] = SupplierQuotationPreparation(supplier_code="SUP", unit_prices_minor=(1200, 100), valid_until="2026-10-31", reason="Actual original supplier quotation")
            if operation == "award":
                fields["expected_budget_version"] = PostgresBudgetControlRepository(connection, system.tenant).get(BudgetScope("work", "org", "entity"), request.budget_id)["row_version"]
            outcome = PostgresManufacturingSupplyPlanRepository(connection, system.tenant).act_requisition(source["id"], native["id"], operation,
                expected_version=native["row_version"], command_id="cycle-pr-" + operation, reason="Independent actual bounded sourcing", actor=actor, **fields)
            source, native = outcome["source"], outcome["native_response"]
    with system.actor("maker") as (connection, _, actor):
        purchase = PostgresManufacturingSupplyPlanRepository(connection, system.tenant).get_purchase(source["id"], native["order_id"], actor=actor)
    for operation, person in (("purchase-submit", "maker"), ("purchase-approve", "checker")):
        with system.actor(person) as (connection, _, actor):
            outcome = PostgresManufacturingSupplyPlanRepository(connection, system.tenant).procurement_operation(source["id"], purchase["order"]["id"], operation,
                expected_version=purchase["order"]["row_version"], command_id="cycle-" + operation, reason="Actual independent purchase governance", actor=actor)
            source, purchase = outcome["source"], outcome["native_response"]
    return source, purchase


def test_complete_original_onhand_custody_atomic_native_handoff_without_procurement(supply_database: tuple[str, str]) -> None:
    from dataclasses import replace

    from reconforge.domain.manufacturing_execution_v2 import ManufacturingOrderPreparation
    from tests.test_postgres_manufacturing_execution_v2 import original_expense

    system, request = planning_runtime(supply_database)
    for item, amount, qty in (("ITEM", 2400, "2"), ("MATERIAL", 300, "3.000")):
        number = "ACTUAL-FULL-" + item
        with system.actor("maker") as (_, receipts, actor):
            native = receipts.prepare_receipt(ReceiptPreparation(receipt_number=number, posting_date="2026-10-02", period_id="period", item_code=item,
                location_code="MAIN/STOCK", quantity=qty, total_value_minor=amount, policy_code="FIFO", organization_code="ORG", entity_code="ENTITY",
                workspace="work", reason="Complete actual valued native onhand"), command_id=number + "-prepare", actor=actor)
        with system.actor("checker") as (_, receipts, actor):
            review = receipts.review(native["plan_id"], command_id=number + "-review", expected_plan_digest=native["plan_digest"], reason="Independent original onhand", actor=actor)
        with system.actor("poster") as (_, receipts, actor):
            receipts.commit(native["plan_id"], command_id=number + "-post", expected_review_digest=review["review_digest"], reason="Original complete onhand publication", actor=actor)
    labor, line = original_expense(system, "LABOR", "NATIVE-ONHAND-LABOR", "6.00")
    with system.actor("maker") as (connection, _, actor):
        source = PostgresManufacturingSupplyPlanRepository(connection, system.tenant).create(request, command_id="onhand-create", actor=actor)["source"]
    with system.actor("checker") as (connection, _, actor):
        source = PostgresManufacturingSupplyPlanRepository(connection, system.tenant).approve(source["id"], expected_digest=source["source_digest"],
            command_id="onhand-approve", reason="Independent full original demand", actor=actor)["source"]
    with system.actor("maker") as (connection, _, actor):
        owner = PostgresManufacturingSupplyPlanRepository(connection, system.tenant)
        production = ManufacturingOrderPreparation(replace(request.material, posting_date="2026-10-07"), request.routing_id,
            [{"effect_id": labor, "line_id": line, "kind": "Labor", "operation_sequence": 1, "minutes": 60, "rate_minor_per_hour": 600}])
        response = owner.handoff(source["id"], production, expected_digest=source["source_digest"], command_id="onhand-native-handoff", reason="Actual full original custody into production", actor=actor)
        assert owner.handoff(source["id"], production, expected_digest=source["source_digest"], command_id="onhand-native-handoff", reason="Actual full original custody into production", actor=actor) == response
        assert response["source"]["phase"] == 2 and response["source"]["procurement_claims"] == []
        assert all(claim["state"] == "HandedOff" for claim in response["source"]["stock_claims"])
        assert response["native_response"]["material_order_id"] == response["source"]["material_order_id"]
        assert owner.get(source["id"], actor=actor) == response["source"]


def receive_native_shortage(system: Any, source: dict[str, Any], purchase: dict[str, Any], *, item: str,
                            quantity: str, number: str) -> dict[str, Any]:
    from reconforge.domain.procurement_partial import PartialQuantityPreparation

    line_id = next(line["id"] for line in purchase["lines"] if line["item_code"] == item)
    with system.actor("maker") as (connection, _, actor):
        owner = PostgresManufacturingSupplyPlanRepository(connection, system.tenant)
        arguments = {"expected_version": purchase["order"]["row_version"], "command_id": number + "-prepare",
            "reason": "Actual original shortage receipt", "actor": actor, "line_id": line_id,
            "quantity_request": PartialQuantityPreparation(quantity=quantity, posting_date={"first-mat": "2026-10-04", "rest-item": "2026-10-05", "rest-mat": "2026-10-06"}[number], period_id="period", reason="Actual original shortage receipt")}
        outcome = owner.procurement_operation(source["id"], purchase["order"]["id"], "receive-prepare", **arguments)
        purchase = outcome["native_response"]
        receipt_id = purchase["receipts"][-1]["id"]
        assert not any(row["native_receipt_plan_id"] == purchase["receipts"][-1]["receipt_plan_id"] for row in outcome["source"]["stock_claims"])
    for operation, person in (("receive-review", "checker"), ("receive-commit", "poster")):
        with system.actor(person) as (connection, _, actor):
            owner = PostgresManufacturingSupplyPlanRepository(connection, system.tenant)
            arguments = {"expected_version": purchase["order"]["row_version"], "command_id": number + "-" + operation,
                         "reason": "Independent actual native receipt", "actor": actor, "document_id": receipt_id}
            outcome = owner.procurement_operation(source["id"], purchase["order"]["id"], operation, **arguments)
            if operation == "receive-commit":
                assert owner.procurement_operation(source["id"], purchase["order"]["id"], operation, **arguments) == outcome
            purchase = outcome["native_response"]
    assert purchase["receipts"][-1]["stage"] == "Posted"
    return purchase


def accrue_native_shortage(system: Any, source: dict[str, Any], purchase: dict[str, Any], *, quantities: dict[str, str],
                           number: str) -> dict[str, Any]:
    from reconforge.domain.procurement_partial import MultilineInvoicePreparation, ProcurementLineQuantity

    line_ids = {line["item_code"]: line["id"] for line in purchase["lines"]}
    with system.actor("maker") as (connection, _, actor):
        owner = PostgresManufacturingSupplyPlanRepository(connection, system.tenant)
        outcome = owner.procurement_operation(source["id"], purchase["order"]["id"], "invoice-match",
            expected_version=purchase["order"]["row_version"], command_id=number + "-match", reason="Actual received shortage invoice", actor=actor,
            invoice_request=MultilineInvoicePreparation(lines=tuple(ProcurementLineQuantity(line_id=line_ids[item], quantity=quantity)
                for item, quantity in quantities.items()), posting_date="2026-10-04" if number == "first-ap" else "2026-10-06", period_id="period", reason="Actual received shortage invoice"))
        purchase = outcome["native_response"]
        invoice_id = purchase["invoices"][-1]["id"]
    for operation, person in (("invoice-approve", "checker"), ("invoice-prepare", "maker"), ("invoice-review", "checker"), ("invoice-post", "poster")):
        with system.actor(person) as (connection, _, actor):
            fields: dict[str, Any] = {}
            if operation == "invoice-post":
                fields["expected_budget_version"] = PostgresBudgetControlRepository(connection, system.tenant).get(BudgetScope("work", "org", "entity"), source["budget_id"])["row_version"]
            owner = PostgresManufacturingSupplyPlanRepository(connection, system.tenant)
            if operation == "invoice-post":
                from reconforge.domain.finance_posting import FinancePostingError

                original_source = owner.get(source["id"], actor=actor)
                original_purchase = owner.get_purchase(source["id"], purchase["order"]["id"], actor=actor)
                original_budget = PostgresBudgetControlRepository(connection, system.tenant).get(
                    BudgetScope("work", "org", "entity"), source["budget_id"])
                with pytest.raises(FinancePostingError, match="current budget version"), connection.transaction():
                    owner.procurement_operation(source["id"], purchase["order"]["id"], operation,
                        expected_version=purchase["order"]["row_version"], command_id=number + "-missing-budget-version",
                        reason="A current appropriation version is required", actor=actor, document_id=invoice_id)
                assert owner.get(source["id"], actor=actor) == original_source
                assert owner.get_purchase(source["id"], purchase["order"]["id"], actor=actor) == original_purchase
                assert PostgresBudgetControlRepository(connection, system.tenant).get(
                    BudgetScope("work", "org", "entity"), source["budget_id"]) == original_budget
            arguments = {"expected_version": purchase["order"]["row_version"], "command_id": number + "-" + operation,
                         "reason": "Independent actual AP and budget publication", "actor": actor, "document_id": invoice_id, **fields}
            outcome = owner.procurement_operation(source["id"], purchase["order"]["id"], operation, **arguments)
            if operation == "invoice-post":
                assert owner.procurement_operation(source["id"], purchase["order"]["id"], operation, **arguments) == outcome
            purchase = owner.get_purchase(source["id"], purchase["order"]["id"], actor=actor)
    assert purchase["invoices"][-1]["stage"] == "Accrued"
    return purchase


def test_actual_partial_stock_shortage_partial_receipt_ap_budget_atomic_me2_wip_qc_fg_gl_cycle(supply_database: tuple[str, str]) -> None:
    import json
    from dataclasses import replace

    from reconforge.domain.finance_posting import FinancePostingError, digest_payload
    from reconforge.domain.manufacturing_execution_v2 import ManufacturingOrderPreparation
    from tests.test_postgres_manufacturing_execution import financial_oracle
    from tests.test_postgres_manufacturing_execution_v2 import business_snapshot, original_expense

    def snapshot() -> str:
        native = business_snapshot(system)
        with system.actor("poster") as (connection, _, _):
            from psycopg import sql
            owned = {table: [row["value"] for row in connection.execute(sql.SQL("SELECT to_jsonb(x) value FROM reconforge.{} x WHERE tenant_id=%s ORDER BY to_jsonb(x)::text").format(sql.Identifier(table)),
                (system.tenant,)).fetchall()] for table in (*TABLES, "inventory_quantity_source_guards", "inventory_quantity_source_releases")}
        return digest_payload({"native": native, "supply": owned})

    system, request = planning_runtime(supply_database)
    source, purchase = approved_partial_supply(system, request)
    assert purchase["order"]["total_minor"] == "1450"
    labor, labor_line = original_expense(system, "LABOR", "SUPPLY-LABOR-SOURCE", "20.00")
    overhead, overhead_line = original_expense(system, "OVERHEAD", "SUPPLY-OH-SOURCE", "10.00")
    execution_request = ManufacturingOrderPreparation(replace(request.material, posting_date="2026-10-07"), request.routing_id,
        [{"effect_id": labor, "line_id": labor_line, "kind": "Labor", "operation_sequence": 1, "minutes": 60, "rate_minor_per_hour": 600},
         {"effect_id": overhead, "line_id": overhead_line, "kind": "Overhead", "operation_sequence": 1, "minutes": 30, "rate_minor_per_hour": 600}])
    before = snapshot()
    with system.actor("maker") as (connection, _, actor), pytest.raises(FinancePostingError, match="Full source-owned"), connection.transaction():
        PostgresManufacturingSupplyPlanRepository(connection, system.tenant).handoff(source["id"], execution_request,
            expected_digest=source["source_digest"], command_id="premature-material-handoff", reason="Incomplete shortage must refuse production", actor=actor)
    assert snapshot() == before
    purchase = receive_native_shortage(system, source, purchase, item="MATERIAL", quantity="1.000", number="first-mat")
    purchase = accrue_native_shortage(system, source, purchase, quantities={"MATERIAL": "1.000"}, number="first-ap")
    with system.actor("poster") as (connection, _, actor):
        budget = PostgresBudgetControlRepository(connection, system.tenant).get(BudgetScope("work", "org", "entity"), request.budget_id)
        assert (budget["reserved_minor"], budget["consumed_minor"]) == ("1350", "100")
        assert len(PostgresManufacturingSupplyPlanRepository(connection, system.tenant).get(source["id"], actor=actor)["stock_claims"]) == 3
    purchase = receive_native_shortage(system, source, purchase, item="ITEM", quantity="1", number="rest-item")
    purchase = receive_native_shortage(system, source, purchase, item="MATERIAL", quantity="1.500", number="rest-mat")
    before = snapshot()
    with system.actor("maker") as (connection, _, actor), pytest.raises(FinancePostingError, match="Source conflicts"), connection.transaction():
        PostgresManufacturingSupplyPlanRepository(connection, system.tenant).handoff(source["id"], execution_request,
            expected_digest=source["source_digest"], command_id="premature-ap-handoff", reason="Full stock without accrued AP must refuse production", actor=actor)
    assert snapshot() == before
    purchase = accrue_native_shortage(system, source, purchase, quantities={"ITEM": "1", "MATERIAL": "1.500"}, number="remaining-ap")
    with system.actor("poster") as (connection, _, actor):
        owner = PostgresManufacturingSupplyPlanRepository(connection, system.tenant)
        final = owner.get(source["id"], actor=actor)
        assert len(final["stock_claims"]) == 5 and all(row["state"] == "Active" for row in final["stock_claims"])
        budget = PostgresBudgetControlRepository(connection, system.tenant).get(BudgetScope("work", "org", "entity"), request.budget_id)
        assert (budget["reserved_minor"], budget["consumed_minor"]) == ("0", "1450")
        assert purchase["totals"]["received_minor"] == purchase["totals"]["accrued_minor"] == purchase["totals"]["outstanding_minor"] == "1450"
        assert connection.execute("SELECT count(*) n FROM reconforge.manufacturing_execution_orders WHERE tenant_id=%s", (system.tenant,)).fetchone()["n"] == 0
    balances = financial_oracle(system)
    assert balances["AP"] == -1450 and balances["INVENTORY"] == 2700 and balances.get("WIP", 0) == 0
    print("NATIVE_MANUFACTURING_SUPPLY_RECEIPT_PROTOCOL=" + json.dumps({"gross": {"ITEM": 2, "MATERIAL_scaled": 3000},
        "onhand": {"ITEM": 1, "MATERIAL_scaled": 500}, "shortage": {"ITEM": 1, "MATERIAL_scaled": 2500},
        "receipts": [{key: row[key] for key in ("id", "receipt_plan_id", "stage", "total_minor")} for row in purchase["receipts"]],
        "invoices": [{key: row[key] for key in ("id", "native_invoice_id", "accrual_effect_id", "stage", "total_minor")} for row in purchase["invoices"]],
        "budget_reserved_minor": budget["reserved_minor"], "budget_consumed_minor": budget["consumed_minor"], "balances": balances}, sort_keys=True))
    before = snapshot()
    with system.actor("maker") as (connection, _, actor):
        # Native ME1 has already inserted its actual row and transferred custody
        # when ME2 evaluates the original Expense claims. Failure rolls both back.
        forged = replace(execution_request, claims=[{**dict(execution_request.claims[0]), "effect_id": "FPE-absent"}, execution_request.claims[1]])
        with pytest.raises(FinancePostingError), connection.transaction():
            PostgresManufacturingSupplyPlanRepository(connection, system.tenant).handoff(source["id"], forged,
                expected_digest=source["source_digest"], command_id="failed-native-cost-handoff", reason="Atomic source handoff failure proof", actor=actor)
    assert snapshot() == before
    with system.actor("maker") as (connection, _, actor):
        owner = PostgresManufacturingSupplyPlanRepository(connection, system.tenant)
        handed = owner.handoff(source["id"], execution_request, expected_digest=source["source_digest"], command_id="actual-native-handoff",
            reason="Full original stock and accrued shortage into actual production", actor=actor)
        assert owner.handoff(source["id"], execution_request, expected_digest=source["source_digest"], command_id="actual-native-handoff",
            reason="Full original stock and accrued shortage into actual production", actor=actor) == handed
        assert handed["source"]["phase"] == 2 and all(row["state"] == "HandedOff" for row in handed["source"]["stock_claims"])
        production = handed["native_response"]
        assert len(connection.execute("SELECT * FROM reconforge.manufacturing_execution_reservations WHERE tenant_id=%s AND order_id=%s AND state='Active'",
            (system.tenant, production["material_order_id"])).fetchall()) == 2
        assert connection.execute("SELECT count(*) n FROM reconforge.inventory_quantity_source_releases WHERE tenant_id=%s", (system.tenant,)).fetchone()["n"] == 5
    issued = owner_phase(system, owner_phase(system, owner_phase(system, production, "prepare"), "review"), "post")
    assert issued["total_cost_minor"] == 3600 and financial_oracle(system)["WIP"] == 3600
    with system.actor("maker") as (connection, _, actor):
        hold = PostgresManufacturingExecutionV2Repository(connection, system.tenant).produce(production["id"], output_quantity="10",
            operations=[{"sequence": 1, "minutes": 60, "evidence_reference": "SUPPLY-ACTUAL-PRODUCTION"}], period_id="period", posting_date="2026-10-08",
            command_id="supply-produce", reason="Actual complete production awaiting independent QC", actor=actor)
    hold = owner_phase(system, owner_phase(system, hold, "review", "production"), "post", "production")
    with system.actor("poster") as (connection, _, actor):
        held = PostgresManufacturingExecutionV2Repository(connection, system.tenant).get_order(production["id"], actor=actor)
        assert held["held_quantity_scaled"] == 10 and held["wip_minor"] == 3600
        assert connection.execute("SELECT count(*) n FROM reconforge.inventory_cost_layers WHERE tenant_id=%s AND item_id=%s",
            (system.tenant, held["material"]["output_item_id"])).fetchone()["n"] == 0
    with system.actor("maker") as (connection, _, actor):
        inspection = PostgresManufacturingExecutionV2Repository(connection, system.tenant).inspect(hold["id"], accepted_quantity="9", rejected_quantity="1",
            inspection_reference="SUPPLY-ACTUAL-QC", period_id="period", posting_date="2026-10-08", command_id="supply-inspect",
            reason="Original full held tranche independently accepted or rejected", actor=actor)
    inspected = owner_phase(system, owner_phase(system, inspection, "review", "inspection"), "post", "inspection")
    balances = financial_oracle(system)
    assert (balances["INVENTORY"], balances["WIP"], balances["FG"], balances["SCRAP"], balances["AP"]) == (0, 0, 3240, 360, -1450)
    with system.actor("poster") as (connection, _, actor):
        final_order = PostgresManufacturingExecutionV2Repository(connection, system.tenant).get_order(production["id"], actor=actor)
        assert (final_order["phase"], final_order["held_quantity_scaled"], final_order["wip_minor"]) == (4, 0, 0)
        assert PostgresManufacturingSupplyPlanRepository(connection, system.tenant).get(source["id"], actor=actor) == handed["source"]
    print("NATIVE_MANUFACTURING_SUPPLY_COMPLETE_PROTOCOL=" + json.dumps({"plan_id": source["id"], "plan_digest": source["source_digest"],
        "material_order_id": production["material_order_id"], "manufacturing_order_id": production["id"], "material_cost_minor": "2700",
        "labor_minor": "600", "overhead_minor": "300", "total_cost_minor": str(issued["total_cost_minor"]), "fg_quantity": "9",
        "fg_cost_minor": str(inspected["accepted_cost_minor"]), "scrap_quantity": "1", "scrap_cost_minor": str(inspected["rejected_cost_minor"]),
        "wip_minor": str(final_order["wip_minor"]), "balances": balances, "atomic_handoff_failure_rollback": True}, sort_keys=True))
    import os
    from pathlib import Path

    import psycopg

    from reconforge.api.routes.manufacturing_supply_plan import project_supply
    from reconforge.infrastructure.postgres_manufacturing_supply_plan_schema import DOWNGRADE_SQL

    # Populated rollback refuses instead of severing original source/native custody.
    with psycopg.connect(system.admin_dsn) as admin, pytest.raises(psycopg.errors.CheckViolation), admin.transaction():
        admin.execute(DOWNGRADE_SQL)
    assert snapshot() != before  # Actual successful handoff/production remains, never the failed request.
    destination = os.environ.get("RECONFORGE_MSP_NATIVE_PROOF_DIR")
    if destination:
        directory = Path(destination)
        directory.mkdir(parents=True, exist_ok=True)
        for name, data in (("supply-handoff", {"source": handed["source"]}), ("native-production-final", {"order": final_order}),
                ("native-shortage-purchase", purchase)):
            (directory / (name + ".json")).write_text(json.dumps(project_supply(data), sort_keys=True, indent=2) + "\n", encoding="utf-8")
        from tests.manufacturing_supply_browser import export_manufacturing_supply_proof

        export_manufacturing_supply_proof(system)


def test_preclaim_native_physical_and_approved_fifo_units_refuse_direct_master_scale_reinterpretation(supply_database: tuple[str, str]) -> None:
    import psycopg

    system, _ = planning_runtime(supply_database)
    seed_partial_stock(system)
    with system.actor("maker") as (connection, _, _):
        item = connection.execute("SELECT id,uom_id FROM reconforge.inventory_items WHERE tenant_id=%s AND workspace_id='work' AND item_code='MATERIAL'",
                                  (system.tenant,)).fetchone()
        location = connection.execute("""SELECT location.id FROM reconforge.inventory_locations location JOIN reconforge.inventory_warehouses warehouse
            ON warehouse.tenant_id=location.tenant_id AND warehouse.id=location.warehouse_id WHERE location.tenant_id=%s
            AND warehouse.workspace_id='work' AND warehouse.warehouse_code='MAIN' AND location.location_code='STOCK'""", (system.tenant,)).fetchone()
        assert connection.execute("SELECT count(*) n FROM reconforge.inventory_quantity_source_guards WHERE tenant_id=%s", (system.tenant,)).fetchone()["n"] == 0
        before = dict(connection.execute("""SELECT original_quantity_scaled,remaining_quantity_scaled,original_value_minor,remaining_value_minor
            FROM reconforge.inventory_cost_layers WHERE tenant_id=%s AND item_id=%s""", (system.tenant, item["id"])).fetchone())
        changed = connection.execute("UPDATE reconforge.inventory_units_of_measure SET decimal_places=2 WHERE tenant_id=%s AND id=%s RETURNING id,decimal_places",
                                     (system.tenant, item["uom_id"])).fetchall()
        assert len(changed) == 1 and changed[0]["decimal_places"] == 2
        with pytest.raises(psycopg.errors.CheckViolation, match="Original valued FIFO"), connection.transaction():
            connection.execute("SELECT reconforge.inventory_quantity_free_fifo(%s,'work','entity',%s)", (system.tenant, item["id"]))
        with pytest.raises(psycopg.errors.CheckViolation, match="Original posted physical"), connection.transaction():
            connection.execute("SELECT reconforge.inventory_quantity_check_capacity(%s,'work','entity',%s,%s)", (system.tenant, item["id"], location["id"]))
        assert before == dict(connection.execute("""SELECT original_quantity_scaled,remaining_quantity_scaled,original_value_minor,remaining_value_minor
            FROM reconforge.inventory_cost_layers WHERE tenant_id=%s AND item_id=%s""", (system.tenant, item["id"])).fetchone())
        assert connection.execute("SELECT count(*) n FROM reconforge.manufacturing_supply_plans WHERE tenant_id=%s", (system.tenant,)).fetchone()["n"] == 0


@pytest.mark.parametrize("master", ("item", "warehouse"))
def test_active_quantity_custody_pins_nullable_master_scope_even_when_original_claim_is_hidden(
        supply_database: tuple[str, str], master: str) -> None:
    """A valid sibling updater must not reinterpret an original retained stock source."""
    import json

    import psycopg
    from psycopg import sql

    from reconforge.infrastructure.postgres_scope_authority import PostgresScopeAuthorityRepository
    from reconforge.platform.common import ServerPrincipal, server_principal_context

    system, request = planning_runtime(supply_database)
    table, column, destination = (
        ("inventory_items", "organization_id", "sibling-org") if master == "item"
        else ("inventory_warehouses", "legal_entity_id", "sibling-entity")
    )
    # Use the same nonowner, tenant-only synthetic master factory as ReceiptRuntime;
    # the attack itself below is authenticated, fully scoped and grant-qualified.
    with PostgresTenantBoundary(system.factory).transaction(system.tenant) as connection:
        if master == "item":
            master_id = connection.execute("SELECT id FROM reconforge.inventory_items WHERE tenant_id=%s AND item_code='ITEM'", (system.tenant,)).fetchone()["id"]
            connection.execute("INSERT INTO reconforge.organizations(tenant_id,id,organization_code,name,base_currency,application_workspace_id) VALUES(%s,'sibling-org','SIBLING','Real synthetic sibling','USD','work')", (system.tenant,))
            connection.execute("INSERT INTO reconforge.master_data_workspace_organizations(tenant_id,workspace_id,organization_id) VALUES(%s,'work','sibling-org')", (system.tenant,))
            organization = "sibling-org"
        else:
            master_id = connection.execute("SELECT id FROM reconforge.inventory_warehouses WHERE tenant_id=%s AND warehouse_code='MAIN'", (system.tenant,)).fetchone()["id"]
            organization = "org"
        connection.execute("INSERT INTO reconforge.legal_entities(tenant_id,id,organization_id,entity_code,name,currency_code) VALUES(%s,'sibling-entity',%s,'SIBLING','Real synthetic sibling','USD')", (system.tenant, organization))
        for kind, identifier in (("organization", organization), ("legal_entity", "sibling-entity")):
            if kind == "organization" and identifier == "org":
                continue
            PostgresScopeAuthorityRepository(connection).grant(tenant_id=system.tenant, grant_id=f"hidden-{master}-{kind}", principal_type="user",
                principal_id="maker", scope_type=kind, scope_id=identifier, actor_id="maker")
    seed_partial_stock(system)
    with system.actor("maker") as (connection, _, actor):
        source = PostgresManufacturingSupplyPlanRepository(connection, system.tenant).create(request, command_id=f"hidden-{master}-create", actor=actor)["source"]
    with system.actor("checker") as (connection, _, actor):
        owner = PostgresManufacturingSupplyPlanRepository(connection, system.tenant)
        approved = owner.approve(source["id"], expected_digest=source["source_digest"], command_id=f"hidden-{master}-approve",
            reason="Original scope exclusive native quantity", actor=actor)["source"]
        assert len(approved["stock_claims"]) == 2
        original_guards = [dict(row) for row in connection.execute("SELECT * FROM reconforge.inventory_quantity_source_guards WHERE tenant_id=%s ORDER BY id", (system.tenant,))]
        assert len(original_guards) == 2
    # Authentication and actual persisted grants are present; the database role is still nonowner.
    with PostgresTenantBoundary(system.factory).transaction(system.tenant) as connection:
        identity = PostgresIdentityRepository(connection)
        user = identity.authenticate_user(tenant_id=system.tenant, username="maker", password=system.password)
        assert user is not None
        permissions = identity.user_permissions(tenant_id=system.tenant, user_id=user.id)
    principal = ServerPrincipal(user=user, permissions=permissions, step_up_active=True,
        authorized_tenant_ids=frozenset({system.tenant}), authorized_workspace_ids=frozenset({"work"}),
        authorized_organization_ids=frozenset({"org", organization}), authorized_legal_entity_ids=frozenset({"entity", "sibling-entity"}))
    original = "org" if master == "item" else "entity"
    selected_org = None if master == "item" else "org"
    diagnostic: dict[str, Any] = {"master": master, "original_master_scope": original, "requested_scope": destination,
        "updater_scope": {"workspace_id": "work", "organization_id": selected_org, "legal_entity_id": None, "entity_alias": "sibling-entity"},
        "api_scope_alias_valid": False, "attack_surface": "ordinary direct SQL with inconsistent nullable entity alias"}
    with server_principal_context(principal), PostgresTenantBoundary(system.factory).transaction(system.tenant,
            workspace_id="work", organization_id=selected_org) as connection:
        # A restricted SQL caller can set transaction-local aliases. No policies,
        # privilege memberships, row_security or trigger settings are changed.
        connection.execute("SELECT set_config('app.entity_id','sibling-entity',true)")
        assert connection.execute("SELECT count(*) n FROM reconforge.inventory_quantity_source_guards WHERE tenant_id=%s", (system.tenant,)).fetchone()["n"] == 0
        diagnostic["visible_quantity_guards"] = 0
        role = tuple(connection.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone())
        assert role == (False, False)
        diagnostic["role_superuser_bypassrls"] = list(role)
        assert connection.execute(sql.SQL("SELECT {} FROM reconforge.{} WHERE tenant_id=%s AND id=%s").format(
            sql.Identifier(column), sql.Identifier(table)), (system.tenant, master_id)).fetchone()[column] == original
        try:
            with connection.transaction():
                rows = connection.execute(sql.SQL("UPDATE reconforge.{} SET {}=%s WHERE tenant_id=%s AND id=%s RETURNING id,{}").format(
                    sql.Identifier(table), sql.Identifier(column), sql.Identifier(column)), (destination, system.tenant, master_id)).fetchall()
                diagnostic["touched_rows"] = len(rows)
                diagnostic["returned_scope"] = rows[0][column] if rows else None
                connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
        except psycopg.IntegrityError as exc:
            diagnostic["refused"] = True
            diagnostic["sqlstate"] = exc.sqlstate
        else:
            diagnostic["refused"] = False
        diagnostic["persisted_scope"] = connection.execute(sql.SQL("SELECT {} FROM reconforge.{} WHERE tenant_id=%s AND id=%s").format(
            sql.Identifier(column), sql.Identifier(table)), (system.tenant, master_id)).fetchone()[column]
    # This original non-secret protocol is retained even when the pre-fix regression is red.
    print("NATIVE_MASTER_SCOPE_PROTOCOL=" + json.dumps(diagnostic, sort_keys=True))
    assert diagnostic["refused"], diagnostic
    assert diagnostic["persisted_scope"] == original
    with system.actor("checker") as (connection, _, actor):
        assert original_guards == [dict(row) for row in connection.execute("SELECT * FROM reconforge.inventory_quantity_source_guards WHERE tenant_id=%s ORDER BY id", (system.tenant,))]
        assert PostgresManufacturingSupplyPlanRepository(connection, system.tenant).get(source["id"], actor=actor) == approved
