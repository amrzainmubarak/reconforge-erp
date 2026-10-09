"""Actual nonowner PostgreSQL stock-to-cash and reservation ownership."""

from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest

from reconforge.domain.finance_posting import FinancePostingError
from reconforge.domain.sales_revenue import SalesInvoicePreparation
from reconforge.domain.stock_sales import StockOrder
from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository
from reconforge.infrastructure.postgres_stock_sales import OPERATION_PERMISSIONS, PostgresStockSalesRepository
from tests.test_postgres_inventory_receipt_posting import ReceiptRuntime, receipt_database, request
from tests.test_postgres_sales_revenue import create_sales_runtime

_ = receipt_database


def repository(connection: Any, runtime: ReceiptRuntime) -> PostgresStockSalesRepository:
    return PostgresStockSalesRepository(connection, runtime.tenant, workspace_id="work", organization_id="org",
                                       legal_entity_id="entity", organization_code="ORG", entity_code="ENTITY")


def create_stock_runtime(database: tuple[str, str], base_runtime: ReceiptRuntime | None = None, *, seed_stock: bool = True) -> ReceiptRuntime:
    runtime = create_sales_runtime(database, base_runtime=base_runtime)
    with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant) as connection:
        identities = PostgresIdentityRepository(connection)
        for permission in sorted(set().union(*OPERATION_PERMISSIONS.values())):
            identities.create_permission(tenant_id=runtime.tenant, permission_name=permission)
            identities.grant_permission(tenant_id=runtime.tenant, role_name="receipt-operator", permission_name=permission)
    if not seed_stock:
        return runtime
    with runtime.actor("maker") as (_, participant, actor):
        plan = participant.prepare_receipt(request(), command_id="inbound-prepare", actor=actor)
    with runtime.actor("checker") as (_, participant, actor):
        review = participant.review(plan["plan_id"], command_id="inbound-review", expected_plan_digest=plan["plan_digest"],
                                   reason="Independent inventory receipt", actor=actor)
    with runtime.actor("poster") as (_, participant, actor):
        participant.commit(plan["plan_id"], command_id="inbound-commit", expected_review_digest=review["review_digest"],
                           reason="Publish actual FIFO stock", actor=actor)
    return runtime


@pytest.fixture
def stock_runtime(receipt_database: tuple[str, str]) -> ReceiptRuntime:
    return create_stock_runtime(receipt_database)


def create_reserved_order(runtime: ReceiptRuntime, number: str = "PRODUCT-1", quantity: str = "5") -> dict[str, Any]:
    with runtime.actor("maker") as (connection, _, actor):
        owner = repository(connection, runtime)
        result = owner.create(StockOrder(number, "CUSTOMER", "CUSTOMER-PO-1", "ITEM", "MAIN", "STOCK", quantity,
                                        5000, "USD", "2026-10-09", "Five physical products", 1000),
                              command_id=number + ":create", actor=actor)
        result = owner.act(result["id"], "submit", expected_version=1, command_id=number + ":submit",
                           reason="Customer terms agreed", parameters={}, actor=actor)
    with runtime.actor("checker") as (connection, _, actor):
        result = repository(connection, runtime).act(result["id"], "approve", expected_version=2,
            command_id=number + ":approve", reason="Approved exact discount and terms", parameters={}, actor=actor)
    with runtime.actor("maker") as (connection, _, actor):
        return repository(connection, runtime).act(result["id"], "reserve", expected_version=3,
            command_id=number + ":reserve", reason="Reserve customer quantity", parameters={}, actor=actor)


def execute(runtime: ReceiptRuntime, result: dict[str, Any], operation: str, actor_name: str,
            parameters: dict[str, Any] | None = None) -> dict[str, Any]:
    with runtime.actor(actor_name) as (connection, _, actor):
        return repository(connection, runtime).act(result["id"], operation, expected_version=result["row_version"],
            command_id=result["number"] + ":" + operation, reason="Actual " + operation, parameters=parameters or {}, actor=actor)


def complete_stock_sale(runtime: ReceiptRuntime) -> dict[str, Any]:
    result = create_reserved_order(runtime)
    result = execute(runtime, result, "prepare-issue", "maker", {
        "posting_date": "2026-10-09", "period_id": "period", "policy_code": "FIFO"})
    result = execute(runtime, result, "review-issue", "checker")
    result = execute(runtime, result, "deliver", "poster")
    invoice = SalesInvoicePreparation("PRODUCT-INVOICE-1", "2026-10-09", "2026-10-31", "SALES", "period",
                                      "AR", "REVENUE", "Actual product sale").payload()
    invoice.pop("reason")
    result = execute(runtime, result, "prepare-invoice", "maker", invoice)
    result = execute(runtime, result, "review-invoice", "checker")
    result = execute(runtime, result, "invoice", "poster")
    result = execute(runtime, result, "prepare-collection", "maker", {
        "receipt_number": "PRODUCT-CASH-1", "receipt_date": "2026-10-10", "journal_code": "CASH",
        "period_id": "period", "cash_account_code": "CASH"})
    result = execute(runtime, result, "review-collection", "checker")
    return execute(runtime, result, "collect", "poster")


def retained_stock_financial_rows(runtime: ReceiptRuntime) -> dict[str, str]:
    from psycopg import sql

    with runtime.actor("maker") as (connection, _, _actor):
        return {table: connection.execute(sql.SQL(
            "SELECT coalesce(jsonb_agg(to_jsonb(r) ORDER BY to_jsonb(r)::text),'[]'::jsonb)::text AS rows "
            "FROM reconforge.{} r WHERE tenant_id=%s").format(sql.Identifier(table)),
            (runtime.tenant,)).fetchone()["rows"] for table in (
                "stock_sales_orders", "stock_sales_reservations", "stock_sales_issue_claims", "stock_sales_commands", "stock_sales_events",
                "inventory_movements", "inventory_movement_lines", "inventory_cost_layers", "inventory_layer_consumptions",
                "inventory_valuation_documents", "inventory_valuation_lines", "finance_entries", "finance_entry_lines",
                "finance_posting_effects", "finance_posting_commands", "operational_finance_plans", "operational_finance_reviews",
                "operational_finance_links", "operational_finance_commands", "ar_invoices", "ar_invoice_lines", "ar_receipts",
                "ar_receipt_allocations", "ar_idempotency_keys", "domain_audit_events", "domain_audit_ledger_state", "outbox_events")}


def test_invoice_and_collection_require_three_humans_in_owner_and_native_sql(
    stock_runtime: ReceiptRuntime, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import psycopg

    runtime = stock_runtime
    result = execute(runtime, create_reserved_order(runtime), "prepare-issue", "maker", {
        "posting_date": "2026-10-09", "period_id": "period", "policy_code": "FIFO"})
    result = execute(runtime, result, "review-issue", "checker")
    result = execute(runtime, result, "deliver", "poster")
    invoice = SalesInvoicePreparation("THREE-HUMAN-INVOICE", "2026-10-09", "2026-10-31", "SALES", "period",
                                      "AR", "REVENUE", "Actual separately posted invoice").payload()
    invoice.pop("reason")
    for kind, operation, parameters in (
        ("invoice", "invoice", invoice),
        ("collection", "collect", {"receipt_number": "THREE-HUMAN-CASH", "receipt_date": "2026-10-10",
            "journal_code": "CASH", "period_id": "period", "cash_account_code": "CASH"}),
    ):
        result = execute(runtime, result, "prepare-" + kind, "maker", parameters)
        result = execute(runtime, result, "review-" + kind, "checker")
        before = retained_stock_financial_rows(runtime)
        for forbidden_actor in ("maker", "checker"):
            with pytest.raises(FinancePostingError) as refusal:
                execute(runtime, result, operation, forbidden_actor)
            assert refusal.value.code == "stock_sales_sod_denied"
            assert retained_stock_financial_rows(runtime) == before
        # Fault injection bypasses only the new Python duty admission. Every
        # native financial participant remains real, exercising SQL closure.
        with monkeypatch.context() as bypass:
            bypass.setattr("reconforge.infrastructure.postgres_stock_sales.require_stock_posting_duties", lambda *_: None)
            with pytest.raises(psycopg.errors.CheckViolation) as native_refusal:
                execute(runtime, result, operation, "checker")
        assert native_refusal.value.sqlstate == "23514"
        assert native_refusal.value.diag.constraint_name == "stock_sales_owner_phase"
        assert retained_stock_financial_rows(runtime) == before
        result = execute(runtime, result, operation, "poster")
        with runtime.actor("poster") as (connection, _, _actor):
            plan_id = result["invoice_plan_id" if kind == "invoice" else "collection_plan_id"]
            actors = connection.execute("""SELECT p.preparer_actor_id,r.reviewer_actor_id,l.posted_actor_id
                FROM reconforge.operational_finance_plans p JOIN reconforge.operational_finance_reviews r
                ON r.tenant_id=p.tenant_id AND r.plan_id=p.id JOIN reconforge.operational_finance_links l
                ON l.tenant_id=p.tenant_id AND l.plan_id=p.id WHERE p.tenant_id=%s AND p.id=%s""",
                (runtime.tenant, plan_id)).fetchone()
            assert dict(actors) == {"preparer_actor_id": "maker", "reviewer_actor_id": "checker", "posted_actor_id": "poster"}
    assert result["status"] == "Paid"


def test_actual_stock_to_cash_has_exact_fifo_cogs_revenue_cash_and_lost_ack(stock_runtime: ReceiptRuntime) -> None:
    runtime = stock_runtime
    result = complete_stock_sale(runtime)
    assert (result["status"], result["row_version"], result["total_minor"], result["cogs_minor"]) == ("Paid", 13, "22500", "6000")
    with runtime.actor("poster") as (connection, _, actor):
        assert repository(connection, runtime).act(result["id"], "collect", expected_version=12,
            command_id="PRODUCT-1:collect", reason="Actual collect", parameters={}, actor=actor) == result
        assert dict(connection.execute("SELECT remaining_quantity_scaled,remaining_value_minor FROM reconforge.inventory_cost_layers WHERE tenant_id=%s",
                                       (runtime.tenant,)).fetchone()) == {"remaining_quantity_scaled": 5, "remaining_value_minor": 6000}
        assert connection.execute("SELECT count(*) n FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 4
        assert connection.execute("SELECT status FROM reconforge.ar_invoices WHERE tenant_id=%s AND id=%s",
                                  (runtime.tenant, result["invoice_id"])).fetchone()["status"] == "Paid"
        assert connection.execute("SELECT state FROM reconforge.stock_sales_reservations WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["state"] == "Consumed"


def test_independent_review_and_native_detached_cogs_rollback(stock_runtime: ReceiptRuntime) -> None:
    runtime = stock_runtime
    result = execute(runtime, create_reserved_order(runtime), "prepare-issue", "maker", {
        "posting_date": "2026-10-09", "period_id": "period", "policy_code": "FIFO"})
    with pytest.raises(FinancePostingError):
        execute(runtime, result, "review-issue", "maker")
    result = execute(runtime, result, "review-issue", "checker")
    import psycopg
    with pytest.raises(psycopg.errors.CheckViolation), runtime.actor("poster") as (connection, _, actor):
        owner = repository(connection, runtime)
        entry = dict(connection.execute("SELECT id,validation_digest FROM reconforge.finance_entries WHERE tenant_id=%s AND id=%s",
                                        (runtime.tenant, result["cogs_entry_id"])).fetchone())
        owner.postings.post(entry["id"], command_id="detached-stock-gl", expected_validation_digest=entry["validation_digest"],
                            reason="Uncoordinated native posting", actor=actor)
    with runtime.actor("maker") as (connection, _, actor):
        assert repository(connection, runtime).get(result["id"], actor=actor)["status"] == "IssueReviewed"
        assert connection.execute("SELECT count(*) n FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 1
    assert execute(runtime, result, "deliver", "poster")["status"] == "Delivered"


def test_cogs_reviewer_cannot_post_delivery_and_third_human_can(stock_runtime: ReceiptRuntime) -> None:
    from psycopg import sql

    runtime = stock_runtime
    result = execute(runtime, create_reserved_order(runtime, "THREE-HUMAN", "5"), "prepare-issue", "maker", {
        "posting_date": "2026-10-09", "period_id": "period", "policy_code": "FIFO"})
    result = execute(runtime, result, "review-issue", "checker")

    def retained_rows() -> dict[str, str]:
        with runtime.actor("maker") as (connection, _, _actor):
            return {table: connection.execute(sql.SQL(
                "SELECT coalesce(jsonb_agg(to_jsonb(r) ORDER BY to_jsonb(r)::text),'[]'::jsonb)::text AS rows "
                "FROM reconforge.{} r WHERE tenant_id=%s").format(sql.Identifier(table)),
                (runtime.tenant,)).fetchone()["rows"] for table in (
                    "stock_sales_orders", "stock_sales_reservations", "stock_sales_issue_claims",
                    "stock_sales_commands", "stock_sales_events", "inventory_movements",
                    "inventory_movement_lines", "inventory_cost_layers", "inventory_layer_consumptions",
                    "inventory_valuation_documents", "inventory_valuation_lines", "finance_entries",
                    "finance_entry_lines", "finance_posting_effects", "domain_audit_events", "outbox_events")}

    before = retained_rows()
    with pytest.raises(FinancePostingError) as refused:
        execute(runtime, result, "deliver", "checker")
    assert refused.value.code == "stock_sales_sod_denied"
    assert retained_rows() == before
    with runtime.actor("maker") as (connection, _, actor):
        assert repository(connection, runtime).get(result["id"], actor=actor) == result
    delivered = execute(runtime, result, "deliver", "poster")
    assert delivered["status"] == "Delivered"
    with runtime.actor("poster") as (connection, _, _actor):
        effect = connection.execute("SELECT posted_actor_id FROM reconforge.finance_posting_effects WHERE tenant_id=%s AND id=%s",
                                    (runtime.tenant, delivered["cogs_effect_id"])).fetchone()
        assert effect["posted_actor_id"] == "poster"


def test_six_concurrent_reservations_cannot_overcommit_ten_units(stock_runtime: ReceiptRuntime) -> None:
    runtime = stock_runtime
    def reserve(index: int) -> bool:
        try:
            create_reserved_order(runtime, "RACE-" + str(index), "3")
            return True
        except Exception as exc:
            import psycopg
            assert isinstance(exc, psycopg.errors.CheckViolation)
            assert exc.diag.constraint_name == "stock_sales_owner_phase"
            return False
    with ThreadPoolExecutor(max_workers=6) as executor:
        assert sum(executor.map(reserve, range(6))) == 3
    with runtime.actor("maker") as (connection, _, _actor):
        assert connection.execute("SELECT sum(quantity_scaled) n FROM reconforge.stock_sales_reservations WHERE tenant_id=%s AND state='Active'",
                                  (runtime.tenant,)).fetchone()["n"] == 9


def test_cancel_releases_actual_capacity_and_retains_voided_unposted_cogs(stock_runtime: ReceiptRuntime) -> None:
    runtime = stock_runtime
    result = execute(runtime, create_reserved_order(runtime, "CANCEL-1", "10"), "prepare-issue", "maker", {
        "posting_date": "2026-10-09", "period_id": "period", "policy_code": "FIFO"})
    with pytest.raises(FinancePostingError, match="Independently review"):
        execute(runtime, result, "cancel", "maker")
    result = execute(runtime, result, "review-issue", "checker")
    cancelled = execute(runtime, result, "cancel", "maker")
    assert cancelled["status"] == "Cancelled"
    with runtime.actor("maker") as (connection, _, actor):
        assert connection.execute("SELECT status FROM reconforge.finance_entries WHERE tenant_id=%s AND id=%s",
                                  (runtime.tenant, result["cogs_entry_id"])).fetchone()["status"] == "Voided"
        assert connection.execute("SELECT count(*) n FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 1
        assert repository(connection, runtime).get(cancelled["id"], actor=actor)["status"] == "Cancelled"
    assert create_reserved_order(runtime, "REPLACEMENT", "10")["status"] == "Reserved"


def test_reserved_quantity_survives_uncoordinated_native_stock_withdrawal(stock_runtime: ReceiptRuntime) -> None:
    import psycopg
    runtime = stock_runtime
    result = create_reserved_order(runtime, "HELD", "10")
    with pytest.raises(psycopg.errors.CheckViolation), runtime.actor("poster") as (connection, _, actor):
        owner = repository(connection, runtime)
        movement = owner.inventory.create_movement(movement_number="UNOWNED-DELIVERY", movement_type="Delivery",
            organization_code="ORG", entity_code="ENTITY", period_id="period", movement_date="2026-10-09",
            description="Native detached withdrawal", source_reference="EXTERNAL", workspace="work", actor_label="maker",
            lines=[{"item_code": "ITEM", "quantity": "1", "from_location": "MAIN/STOCK"}])
        owner.inventory.post_movement(movement["id"], reason="Bypass reserved stock", actor_label=actor.username)
    with runtime.actor("maker") as (connection, _, actor):
        assert repository(connection, runtime).get(result["id"], actor=actor)["status"] == "Reserved"
        assert connection.execute("SELECT count(*) n FROM reconforge.inventory_movements WHERE tenant_id=%s AND movement_number='UNOWNED-DELIVERY'",
                                  (runtime.tenant,)).fetchone()["n"] == 0


def test_owner_reference_cannot_publish_a_detached_native_delivery(stock_runtime: ReceiptRuntime) -> None:
    import psycopg
    runtime = stock_runtime
    result = execute(runtime, create_reserved_order(runtime, "FROZEN-REFERENCE", "5"), "prepare-issue", "maker", {
        "posting_date": "2026-10-09", "period_id": "period", "policy_code": "FIFO"})
    result = execute(runtime, result, "review-issue", "checker")
    with pytest.raises(psycopg.errors.CheckViolation):
        with runtime.actor("maker") as (connection, _, actor):
            movement = repository(connection, runtime).inventory.create_movement(movement_number="DETACHED-OWNER-REFERENCE", movement_type="Delivery",
                organization_code="ORG", entity_code="ENTITY", period_id="period", movement_date="2026-10-09",
                description="Native movement claiming the frozen source", source_reference=result["id"], workspace="work", actor_label=actor.username,
                lines=[{"item_code": "ITEM", "quantity": "1", "from_location": "MAIN/STOCK"}])
        with runtime.actor("poster") as (connection, _, actor):
            repository(connection, runtime).inventory.post_movement(movement["id"], reason="Uncoordinated owner reference", actor_label=actor.username)
    with runtime.actor("maker") as (connection, _, actor):
        assert repository(connection, runtime).get(result["id"], actor=actor)["status"] == "IssueReviewed"
        assert connection.execute("SELECT count(*) n FROM reconforge.inventory_movements WHERE tenant_id=%s AND movement_number='DETACHED-OWNER-REFERENCE'",
                                  (runtime.tenant,)).fetchone()["n"] == 0
    assert execute(runtime, result, "deliver", "poster")["status"] == "Delivered"


def test_owner_reference_cannot_publish_an_extra_manual_financial_effect(stock_runtime: ReceiptRuntime) -> None:
    import psycopg
    runtime = stock_runtime
    result = execute(runtime, create_reserved_order(runtime, "FROZEN-FINANCE", "5"), "prepare-issue", "maker", {
        "posting_date": "2026-10-09", "period_id": "period", "policy_code": "FIFO"})
    result = execute(runtime, result, "review-issue", "checker")
    with pytest.raises(psycopg.errors.CheckViolation):
        with runtime.actor("maker") as (connection, _, actor):
            extra = repository(connection, runtime).finance.create_entry(entry_number="EXTRA-MANUAL-STOCK-REF", organization_code="ORG",
                entity_code="ENTITY", period_id="period", journal_code="STOCK", posting_date="2026-10-09", description="Extra claimed stock cost",
                external_reference=result["id"], source_type="Manual", workspace="work", actor_label=actor.username,
                lines=[{"account_code": "COGS", "debit": "1.00", "credit": "0"}, {"account_code": "INVENTORY", "debit": "0", "credit": "1.00"}])
        with runtime.actor("checker") as (connection, _, actor):
            repository(connection, runtime).finance.validate_entry(extra["id"], reason="Independent native review", actor_label=actor.username)
        with runtime.actor("poster") as (connection, _, actor):
            seal = connection.execute("SELECT validation_digest FROM reconforge.finance_entries WHERE tenant_id=%s AND id=%s",
                                      (runtime.tenant, extra["id"])).fetchone()["validation_digest"]
            repository(connection, runtime).postings.post(extra["id"], command_id="extra-stock-ref", expected_validation_digest=seal,
                                                        reason="Uncoordinated owner reference", actor=actor)
    with runtime.actor("maker") as (connection, _, actor):
        assert repository(connection, runtime).get(result["id"], actor=actor)["status"] == "IssueReviewed"
        assert connection.execute("SELECT count(*) n FROM reconforge.finance_entries WHERE tenant_id=%s AND entry_number='EXTRA-MANUAL-STOCK-REF'",
                                  (runtime.tenant,)).fetchone()["n"] == 0
        assert connection.execute("SELECT count(*) n FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 1
    assert execute(runtime, result, "deliver", "poster")["status"] == "Delivered"


def test_raw_forged_phase_requires_native_issue_and_auditable_command(stock_runtime: ReceiptRuntime) -> None:
    import psycopg
    runtime = stock_runtime
    result = create_reserved_order(runtime)
    with pytest.raises(psycopg.errors.CheckViolation), runtime.actor("maker") as (connection, _, actor):
        owner = repository(connection, runtime)
        owner._actor(actor, "prepare-issue", owner._order(result["id"]))
        connection.execute("UPDATE reconforge.stock_sales_orders SET status='IssuePrepared',row_version=row_version+1 WHERE tenant_id=%s AND id=%s",
                           (runtime.tenant, result["id"]))
    with runtime.actor("maker") as (connection, _, actor):
        assert repository(connection, runtime).get(result["id"], actor=actor)["status"] == "Reserved"


def test_exact_scope_is_hidden_and_raw_stock_dml_is_denied(stock_runtime: ReceiptRuntime) -> None:
    import psycopg
    runtime = stock_runtime
    result = create_reserved_order(runtime)
    with runtime.actor("maker") as (connection, _, _actor):
        connection.execute("SELECT set_config('app.organization_id','foreign',true)")
        assert connection.execute("SELECT id FROM reconforge.stock_sales_orders WHERE tenant_id=%s", (runtime.tenant,)).fetchall() == []
    with pytest.raises(psycopg.errors.CheckViolation), runtime.actor("maker") as (connection, _, actor):
        owner = repository(connection, runtime)
        row = owner._order(result["id"])
        owner._actor(actor, "reserve", row)
        connection.execute("SELECT set_config('app.organization_id','foreign',true)")
        connection.execute("INSERT INTO reconforge.stock_sales_reservations(tenant_id,order_id,workspace_id,organization_id,legal_entity_id,location_id,item_id,quantity_scaled) VALUES(%s,%s,'work','foreign','entity',%s,%s,%s)",
                           (runtime.tenant, result["id"], row["location_id"], row["item_id"], row["quantity_scaled"]))
