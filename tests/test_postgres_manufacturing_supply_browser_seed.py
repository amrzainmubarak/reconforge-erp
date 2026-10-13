"""Actual native browser seed retains only approved originals, never completed docs."""
from typing import Any

import pytest

from reconforge.domain.finance_posting import FinancePostingError
from reconforge.infrastructure.postgres_manufacturing_supply_plan import PostgresManufacturingSupplyPlanRepository
from tests.manufacturing_supply_browser import (
    MANUFACTURING_SUPPLY_TAMPER,
    manufacturing_supply_browser_configuration,
    manufacturing_supply_proof,
    seed_manufacturing_supply_browser,
)
from tests.test_postgres_manufacturing_supply_plan import (
    baseline_manufacturing_v2_database,
    baseline_receipt_database,
    original_manufacturing_database,
    planning_runtime,
    supply_database,
)

_ = (baseline_manufacturing_v2_database, baseline_receipt_database, original_manufacturing_database, supply_database)


def test_actual_native_seed_has_original_partial_stock_expenses_and_zero_planned_purchase_or_production_docs(supply_database: tuple[str, str]) -> None:
    runtime = seed_manufacturing_supply_browser(*supply_database)
    config = manufacturing_supply_browser_configuration(runtime)
    proof: dict[str, Any] = manufacturing_supply_proof(runtime)
    tables = proof["populations"]
    assert tables["manufacturing_supply_plans"] == tables["procurement_sourcing_requisitions"] == tables["procurement_partial_orders"] == []
    assert tables["manufacturing_execution_orders"] == tables["manufacturing_execution_v2_orders"] == []
    assert config["bom_version_id"] == tables["manufacturing_execution_boms"][0]["id"]
    assert tables["manufacturing_execution_boms"][0]["phase"] == 1
    assert config["routing_id"] in {row["id"] for row in tables["manufacturing_execution_v2_definitions"] if row["kind"] == "Routing" and row["phase"] == 1}
    assert config["budget_id"] == tables["budget_envelopes"][0]["id"] and tables["budget_envelopes"][0]["status"] == "Approved"
    items = {row["id"]: row["item_code"] for row in tables["inventory_items"]}
    assert {items[row["item_id"]]: (row["original_quantity_scaled"], row["original_value_minor"]) for row in tables["inventory_cost_layers"]} == {"ITEM": (1, 1200), "MATERIAL": (500, 50)}
    assert [(row["kind"], row["minutes"], row["rate_minor_per_hour"]) for row in config["cost_claims"]] == [("Labor", 60, "600"), ("Overhead", 30, "600")]
    assert len(tables["finance_posting_effects"]) == 4 and len(MANUFACTURING_SUPPLY_TAMPER) == 3
    with runtime.actor("browser-maker") as (_, _, maker), runtime.actor("browser-checker") as (_, _, checker), runtime.actor("browser-poster") as (_, _, poster):
        assert (maker.user_id, checker.user_id, poster.user_id) == ("erp-maker", "erp-checker", "erp-poster")
    assert proof["capture"]["role_superuser"] is False and proof["capture"]["role_bypassrls"] is False


def test_actual_original_command_receipt_replays_historical_approval_after_cancel_and_refuses_wrong_actor_or_response(supply_database: tuple[str, str]) -> None:
    runtime, request = planning_runtime(supply_database)
    with runtime.actor("maker") as (connection, _, actor):
        outcome = PostgresManufacturingSupplyPlanRepository(connection, runtime.tenant).create(request, command_id="receipt-create", actor=actor)
    source = outcome["source"]
    arguments = {"expected_digest": source["source_digest"], "command_id": "receipt-approve", "reason": "Exact independent receipt approval"}
    with runtime.actor("checker") as (connection, _, actor):
        owner = PostgresManufacturingSupplyPlanRepository(connection, runtime.tenant)
        approved = owner.approve(source["id"], **arguments, actor=actor)
        receipt = owner.command_receipt(source["id"], arguments["command_id"], approved, actor=actor)
        assert (receipt["version"], receipt["operation"], receipt["actor_id"], receipt["native_kind"]) == (2, "approve", "checker", None)
    with runtime.actor("checker") as (connection, _, actor):
        owner = PostgresManufacturingSupplyPlanRepository(connection, runtime.tenant)
        cancelled = owner.cancel(source["id"], expected_digest=source["source_digest"], command_id="receipt-cancel", reason="Retain later terminal history", actor=actor)
        assert cancelled["source"]["phase"] == 3 and cancelled["source"]["row_version"] == 3
    with runtime.actor("checker") as (connection, _, actor):
        owner = PostgresManufacturingSupplyPlanRepository(connection, runtime.tenant)
        assert owner.approve(source["id"], **arguments, actor=actor) == approved
        assert owner.command_receipt(source["id"], arguments["command_id"], approved, actor=actor) == receipt
        with pytest.raises(FinancePostingError), connection.transaction():
            owner.command_receipt(source["id"], arguments["command_id"], cancelled, actor=actor)
    with runtime.actor("poster") as (connection, _, actor), pytest.raises(FinancePostingError), connection.transaction():
        PostgresManufacturingSupplyPlanRepository(connection, runtime.tenant).command_receipt(source["id"], arguments["command_id"], approved, actor=actor)
