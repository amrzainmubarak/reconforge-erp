"""Actual ME1 requirement provenance into source-owned native budget procurement."""
from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from reconforge.domain.budget_control import BudgetControlError
from reconforge.domain.finance_posting import FinancePostingError, digest_payload
from reconforge.domain.inventory_receipt_posting import ReceiptPreparation
from reconforge.domain.manufacturing_execution import PERMISSIONS as MANUFACTURING_PERMISSIONS
from reconforge.domain.manufacturing_execution import BomPreparation, OrderPreparation
from reconforge.domain.procurement_sourcing import (
    RequirementReference,
    RequisitionPreparation,
    SupplierQuotationPreparation,
)
from reconforge.infrastructure.postgres_finance_core import PostgresFinanceCoreRepository
from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository
from reconforge.infrastructure.postgres_inventory_core import PostgresInventoryCoreRepository
from reconforge.infrastructure.postgres_inventory_valuation import PostgresInventoryValuationRepository
from reconforge.infrastructure.postgres_manufacturing_execution import PostgresManufacturingExecutionRepository
from reconforge.infrastructure.postgres_procurement_sourcing import PostgresProcurementSourcingRepository
from tests.test_postgres_procurement_multiline import action, invoice_lines, receive_line
from tests.test_postgres_procurement_partial import CHECKER, MAKER, POSTER
from tests.test_postgres_procurement_sourcing import receipt_database, source_digest, sourcing_runtime, stage
from tests.test_procurement_multiline import enterprise_request

__all__ = ["receipt_database", "sourcing_runtime"]


def manufacturing_requirement_source(runtime: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    with runtime.actor(MAKER) as (connection, _, _):
        identity = PostgresIdentityRepository(connection)
        for permission in sorted(set().union(*MANUFACTURING_PERMISSIONS.values())):
            identity.create_permission(tenant_id=runtime.tenant, permission_name=permission)
            identity.grant_permission(tenant_id=runtime.tenant, role_name="receipt-operator", permission_name=permission)
        finance = PostgresFinanceCoreRepository(connection, runtime.tenant)
        for code, kind in (("WIP", "Asset"), ("FG", "Asset"), ("SCRAP", "Expense")):
            finance.upsert_account(account_code=code, name=code, account_type=kind, chart_code="DEFAULT", workspace="work")
        PostgresInventoryCoreRepository(connection, runtime.tenant).upsert_item(item_code="PRODUCT", name="Synthetic actual output",
            organization_code="ORG", uom_code="EA", inventory_account_code="FG", workspace="work")
        PostgresInventoryValuationRepository(connection, runtime.tenant).upsert_policy(policy_code="MFG", organization_code="ORG",
            entity_code="ENTITY", journal_code="STOCK", receipt_clearing_account_code="WIP", cogs_account_code="COGS",
            adjustment_account_code="ADJUSTMENT", workspace="work")
    for number, item, qty, amount in (("LINK-SEED-A", "ITEM", "10", 12000), ("LINK-SEED-B", "WEIGHT", "20.00", 3333)):
        with runtime.actor(MAKER) as (_, receipts, actor):
            plan = receipts.prepare_receipt(ReceiptPreparation(receipt_number=number, posting_date="2026-10-02", period_id="period",
                item_code=item, location_code="MAIN/STOCK", quantity=qty, total_value_minor=amount, policy_code="FIFO",
                organization_code="ORG", entity_code="ENTITY", workspace="work", reason="Original independently posted materials"),
                command_id=number + "-prepare", actor=actor)
        with runtime.actor(CHECKER) as (_, receipts, actor):
            review = receipts.review(plan["plan_id"], expected_plan_digest=plan["plan_digest"], command_id=number + "-review",
                reason="Original exact stock backing", actor=actor)
        with runtime.actor(POSTER) as (_, receipts, actor):
            receipts.commit(plan["plan_id"], expected_review_digest=review["review_digest"], command_id=number + "-post",
                reason="Original native receipt publication", actor=actor)
    with runtime.actor(MAKER) as (connection, _, actor):
        bom = PostgresManufacturingExecutionRepository(connection, runtime.tenant).prepare_bom(BomPreparation(number="LINK-BOM", version=1,
            output_item_code="PRODUCT", output_quantity="10", components=[{"item_code": "ITEM", "quantity": "2"}, {"item_code": "WEIGHT", "quantity": "2.50"}],
            workspace_id="work", organization_id="org", legal_entity_id="entity", organization_code="ORG", entity_code="ENTITY",
            reason="Actual canonical versioned procurement demand"), command_id="link-bom-create", actor=actor)
    with runtime.actor(CHECKER) as (connection, _, actor):
        bom = PostgresManufacturingExecutionRepository(connection, runtime.tenant).approve_bom(bom["id"], expected_digest=bom["source_digest"],
            command_id="link-bom-approve", reason="Independent original recipe approval", actor=actor)
    with runtime.actor(MAKER) as (connection, _, actor):
        owner = PostgresManufacturingExecutionRepository(connection, runtime.tenant)
        order = owner.create_order(OrderPreparation(number="LINK-PRODUCTION", bom_version_id=bom["id"], output_quantity="10",
            component_location_code="MAIN/STOCK", finished_location_code="MAIN/STOCK", component_policy_code="FIFO", finished_policy_code="MFG",
            journal_code="STOCK", wip_account_code="WIP", scrap_account_code="SCRAP", period_id="period", posting_date="2026-10-03",
            workspace_id="work", organization_id="org", legal_entity_id="entity", organization_code="ORG", entity_code="ENTITY",
            reason="Actual retained source reservation"), command_id="link-order-create", actor=actor)
        order = owner.act(order["id"], "prepare", expected_digest=order["source_digest"], command_id="link-order-prepare",
            reason="Retain full parent cost for linked read authority", actor=actor)
        requirements = {line["item_code"]: owner.get_requirement(line["requirement_id"], actor=actor) for line in order["requirements"]}
    return order, requirements


def linked_request(budget: dict[str, Any], requirements: dict[str, Any], *, number: str = "SRC5-ME1") -> RequisitionPreparation:
    order = enterprise_request(number)
    order = replace(order, lines=(replace(order.lines[0], quantity="2"), order.lines[1]))
    return RequisitionPreparation(budget_id=budget["id"], order=order, reason="Original canonical manufacturing demand provenance",
        requirements=tuple(RequirementReference(requirement_id=requirements[line.item_code]["requirement_id"],
            requirement_digest=requirements[line.item_code]["requirement_digest"]) for line in order.lines))


def test_actual_manufacturing_requirement_to_reviewed_sourcing_budget_receipt_and_ap(
    sourcing_runtime: tuple[Any, dict[str, Any]],
) -> None:
    runtime, budget = sourcing_runtime
    production, requirements = manufacturing_requirement_source(runtime)
    request = linked_request(budget, requirements)
    with runtime.actor(MAKER) as (connection, _, actor):
        repository = PostgresProcurementSourcingRepository(connection, runtime.tenant)
        head = repository.create(request, command_id="linked-source-create", actor=actor)
        assert repository.create(request, command_id="linked-source-create", actor=actor) == head
        detail = repository.get(head["id"], actor=actor)
        for retained in detail["source"]["manufacturing_requirements"]:
            native = requirements[retained["item_code"]]
            assert retained["requirement_digest"] == digest_payload({key: value for key, value in native.items() if key != "requirement_digest"})
            assert retained["order_source_digest"] == production["source_digest"]
            assert retained["bom_version_id"] == production["bom_version_id"]
    head = stage(runtime, head, "open-rfq", CHECKER)
    for supplier, prices in (("ALT", (1300, 2000)), ("SUP", (1200, 2000))):
        with runtime.actor(MAKER) as (connection, _, actor):
            head = PostgresProcurementSourcingRepository(connection, runtime.tenant).record_quotation(head["id"],
                SupplierQuotationPreparation(supplier_code=supplier, unit_prices_minor=prices, valid_until="2026-10-31", reason="Retained actual linked supplier offer"),
                expected_version=head["row_version"], command_id="linked-quote-" + supplier, actor=actor)
    head = stage(runtime, head, "review-selection", CHECKER)
    head = stage(runtime, head, "award", POSTER, expected_budget_version=budget["row_version"])
    with runtime.actor(POSTER) as (connection, _, actor):
        repository = PostgresProcurementSourcingRepository(connection, runtime.tenant)
        purchase = repository.purchase.get(head["order_id"], actor=actor)
        owner = repository.commitments.get(head["order_id"], actor=actor)
        assert (owner["original_minor"], owner["reserved_minor"]) == ("7400", "7400")
    purchase = action(runtime, action(runtime, purchase, "submit-order", POSTER), "approve-order", CHECKER)
    purchase = receive_line(runtime, purchase, 0, "2")
    purchase = receive_line(runtime, purchase, 1, "2.50")
    purchase = invoice_lines(runtime, purchase, ((0, "2"), (1, "2.50")))
    invoice = purchase["invoices"][-1]["id"]
    for operation, name in (("approve-invoice", CHECKER), ("prepare-accrual", MAKER), ("review-accrual", CHECKER)):
        purchase = action(runtime, purchase, operation, name, invoice)
    with runtime.actor(POSTER) as (connection, _, actor):
        repository = PostgresProcurementSourcingRepository(connection, runtime.tenant)
        consumed = repository.commitments.consume_invoice(head["order_id"], invoice, expected_order_version=purchase["order"]["row_version"],
            expected_budget_version=owner["budget_version"], command_id="linked-consume", reason="Original provenance into native AP and appropriation", actor=actor)
        assert (consumed["reserved_minor"], consumed["consumed_minor"]) == ("0", "7400")
        # Independent integer arithmetic: 2 EA *1200 +250 hundredths KG *2000/100.
        assert 2 * 1200 + 250 * 2000 // 100 == 7400
        native = repository.purchase.get(head["order_id"], actor=actor)["invoices"][-1]["native_invoice_id"]
        assert connection.execute("SELECT total_minor,status FROM reconforge.ap_supplier_invoices WHERE tenant_id=%s AND id=%s", (runtime.tenant, native)).fetchone()["total_minor"] == 7400
        assert connection.execute("SELECT count(*) n FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 5


@pytest.mark.parametrize("mismatch", ("item", "quantity", "digest", "scope"))
def test_actual_manufacturing_link_refuses_changed_item_quantity_digest_or_scope(
    sourcing_runtime: tuple[Any, dict[str, Any]], mismatch: str,
) -> None:
    runtime, budget = sourcing_runtime
    _, requirements = manufacturing_requirement_source(runtime)
    request = linked_request(budget, requirements)
    if mismatch == "item":
        request = replace(request, requirements=tuple(reversed(request.requirements)))
    elif mismatch == "quantity":
        request = replace(request, order=replace(request.order, lines=(replace(request.order.lines[0], quantity="3"), request.order.lines[1])))
    elif mismatch == "digest":
        request = replace(request, requirements=(replace(request.requirements[0], requirement_digest="0" * 64), request.requirements[1]))
    before = source_digest(runtime)
    with runtime.actor(MAKER) as (connection, _, actor):
        repository = PostgresProcurementSourcingRepository(connection, runtime.tenant)
        with pytest.raises((FinancePostingError, BudgetControlError, ValueError)):
            if mismatch == "scope":
                # The actual source getter sees current native RLS isolation, not an injected source stub.
                connection.execute("SELECT set_config('app.legal_entity_id','foreign',true)")
            repository.create(request, command_id="linked-source-create", actor=actor)
    assert source_digest(runtime) == before


def test_linked_source_read_and_lost_ack_recheck_current_parent_permission_and_full_cost(
    sourcing_runtime: tuple[Any, dict[str, Any]], monkeypatch: pytest.MonkeyPatch,
) -> None:
    from decimal import Decimal

    from reconforge.auth.policy import evaluate_principal_access
    from reconforge.infrastructure import postgres_operational_finance

    runtime, budget = sourcing_runtime
    production, requirements = manufacturing_requirement_source(runtime)
    request = linked_request(budget, requirements)
    with runtime.actor(MAKER) as (connection, _, actor):
        head = PostgresProcurementSourcingRepository(connection, runtime.tenant).create(request, command_id="linked-source-create", actor=actor)
    before = source_digest(runtime)
    observed: list[Decimal | None] = []

    def bounded_policy(*args: Any, **kwargs: Any) -> Any:
        observed.append(kwargs.get("amount"))
        return evaluate_principal_access(*args, **kwargs, maximum_amount=Decimal("1.00"))

    with monkeypatch.context() as selected:
        selected.setattr(postgres_operational_finance, "evaluate_principal_access", bounded_policy)
        for operation in ("read", "replay"):
            with runtime.actor(MAKER) as (connection, _, actor), pytest.raises(FinancePostingError):
                repository = PostgresProcurementSourcingRepository(connection, runtime.tenant)
                if operation == "read":
                    repository.get(head["id"], actor=actor)
                else:
                    repository.create(request, command_id="linked-source-create", actor=actor)
        assert any(amount == Decimal(production["issue_plan"]["total_cost_minor"]) / 100 for amount in observed)
    assert source_digest(runtime) == before
    with runtime.actor(CHECKER) as (connection, _, _):
        connection.execute("UPDATE reconforge.identity_role_permissions SET active=FALSE,lifecycle_version=lifecycle_version+1,revoked_at=now(),revoked_by=%s,revocation_reason_code='access_change' WHERE tenant_id=%s AND permission_name='manufacturing_execution.read'",
            ("id-" + CHECKER, runtime.tenant))
    for operation in ("read", "replay"):
        with runtime.actor(MAKER) as (connection, _, actor), pytest.raises(FinancePostingError):
            repository = PostgresProcurementSourcingRepository(connection, runtime.tenant)
            if operation == "read":
                repository.get(head["id"], actor=actor)
            else:
                repository.create(request, command_id="linked-source-create", actor=actor)
