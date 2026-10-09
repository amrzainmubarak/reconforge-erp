"""Real individual-invoice partial receipts and immutable cash ownership."""
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest

from reconforge.domain.commercial_collections import CommercialCollectionPreparation
from reconforge.domain.finance_posting import FinancePostingError
from reconforge.infrastructure.postgres_commercial_collections import PostgresCommercialCollectionsRepository
from tests.test_postgres_inventory_receipt_posting import ReceiptRuntime, receipt_database
from tests.test_postgres_stock_commerce import act, commercial_order, repository
from tests.test_postgres_stock_sales import create_stock_runtime

_ = receipt_database


def invoiced(runtime: ReceiptRuntime) -> tuple[dict[str, Any], str]:
    result = commercial_order(runtime)
    result = act(runtime, result, "open-tranche", "maker", {"line_number": 1, "quantity": "10"})
    tranche = result["lines"][0]["tranches"][0]["id"]
    for operation, who, values in (
        ("approve-tranche", "checker", {}),
        ("prepare-issue", "maker", {"posting_date": "2026-10-09", "period_id": "period", "policy_code": "FIFO"}),
        ("review-issue", "checker", {}), ("deliver", "poster", {}),
        ("prepare-invoice", "maker", {"invoice_number": "PARTIAL-AR", "invoice_date": "2026-10-09", "due_date": "2026-10-31",
            "journal_code": "SALES", "period_id": "period", "receivable_account_code": "AR", "revenue_account_code": "REVENUE"}),
        ("review-invoice", "checker", {}), ("invoice", "poster", {}),
    ):
        result = act(runtime, result, operation, who, {"tranche_id": tranche, **values})
    return result, result["lines"][0]["tranches"][0]["invoice_id"]


def prepare(runtime: ReceiptRuntime, invoice_id: str, amount: int, suffix: str = "FIRST") -> dict[str, Any]:
    with runtime.actor("maker") as (connection, _, actor):
        owner = PostgresCommercialCollectionsRepository(connection, runtime.tenant)
        request = CommercialCollectionPreparation(workspace_id="work", organization_id="org", legal_entity_id="entity",
            organization_code="ORG", entity_code="ENTITY", source_id=invoice_id, journal_code="CASH", period_id="period",
            posting_date="2026-10-10", debit_account_code="CASH", credit_account_code="AR", reason="Actual partial AR collection",
            amount_minor=amount, receipt_number="PARTIAL-CASH-" + suffix)
        result = owner.prepare(request, command_id="prepare-" + suffix, actor=actor)
        assert owner.prepare(request, command_id="prepare-" + suffix, actor=actor) == result
        return result


def phase(runtime: ReceiptRuntime, plan: dict[str, Any], operation: str, who: str, command: str) -> dict[str, Any]:
    with runtime.actor(who) as (connection, _, actor):
        owner = PostgresCommercialCollectionsRepository(connection, runtime.tenant)
        method = getattr(owner, operation)
        args = {"expected_plan_digest": plan["plan_digest"], "command_id": command,
                "reason": "Independent actual " + operation, "actor": actor}
        result = method(plan["id"], **args)
        assert method(plan["id"], **args) == result
        return result


def complete(runtime: ReceiptRuntime, plan: dict[str, Any], suffix: str) -> dict[str, Any]:
    return phase(runtime, phase(runtime, plan, "review", "checker", "review-" + suffix), "post", "poster", "post-" + suffix)


def test_three_partial_receipts_inside_one_invoice_conserve_independent_cash_ar_and_cogs(receipt_database: tuple[str, str]) -> None:
    runtime = create_stock_runtime(receipt_database)
    order, invoice_id = invoiced(runtime)
    expected = (10000, 15000, 20000)
    posted = [complete(runtime, prepare(runtime, invoice_id, amount, str(index)), str(index)) for index, amount in enumerate(expected)]
    with runtime.actor("maker") as (connection, _, actor):
        result = repository(connection, runtime).get(order["id"], actor=actor)
        line, tranche = result["lines"][0], result["lines"][0]["tranches"][0]
        assert line["collected_minor"] == "45000"
        assert tranche["invoice_id"] == invoice_id and tranche["invoice_status"] == "Paid"
        assert tranche["collected_minor"] == "45000" and tranche["outstanding_minor"] == "0"
        assert tranche["status"] == "Invoiced" and tranche["pending_collection"] is None
        receipts = connection.execute("SELECT amount_minor FROM reconforge.ar_receipts WHERE tenant_id=%s ORDER BY amount_minor", (runtime.tenant,)).fetchall()
        assert [row["amount_minor"] for row in receipts] == list(expected)
        totals = {row["account_code"]: (int(row["d"]), int(row["c"])) for row in connection.execute(
            """SELECT a.account_code,sum(l.debit_minor) d,sum(l.credit_minor) c FROM reconforge.finance_posting_effects f
            JOIN reconforge.finance_entry_lines l ON l.tenant_id=f.tenant_id AND l.entry_id=f.entry_id
            JOIN reconforge.finance_accounts a ON a.tenant_id=l.tenant_id AND a.id=l.account_id
            WHERE f.tenant_id=%s GROUP BY a.account_code""", (runtime.tenant,)).fetchall()}
        assert totals["CASH"] == (45000, 0) and totals["AR"] == (45000, 45000)
        assert totals["REVENUE"] == (0, 45000) and totals["COGS"] == (12000, 0)
        assert len({row["posting_effect_id"] for row in posted}) == 3
        assert connection.execute("SELECT sum(remaining_quantity_scaled) q FROM reconforge.inventory_cost_layers WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["q"] == 0
    with pytest.raises(FinancePostingError, match="positive residual"):
        prepare(runtime, invoice_id, 1, "EXCESS")


def test_partial_view_pending_claim_overpayment_and_three_person_duties(receipt_database: tuple[str, str]) -> None:
    runtime = create_stock_runtime(receipt_database)
    order, invoice_id = invoiced(runtime)
    with pytest.raises(FinancePostingError, match="residual"):
        prepare(runtime, invoice_id, 45001)
    plan = prepare(runtime, invoice_id, 10000)
    with pytest.raises(FinancePostingError, match="pending"):
        prepare(runtime, invoice_id, 5000, "OTHER")
    with pytest.raises(FinancePostingError, match="independent"):
        phase(runtime, plan, "review", "maker", "self-review")
    reviewed = phase(runtime, plan, "review", "checker", "review")
    for who in ("maker", "checker"):
        with pytest.raises(FinancePostingError, match="third authorized human"):
            phase(runtime, reviewed, "post", who, "self-post-" + who)
    phase(runtime, reviewed, "post", "poster", "post")
    with runtime.actor("maker") as (connection, _, actor):
        view = repository(connection, runtime).get(order["id"], actor=actor)
        tranche = view["lines"][0]["tranches"][0]
        assert (tranche["invoice_status"], tranche["collected_minor"], tranche["outstanding_minor"]) == ("PartiallyPaid", "10000", "35000")
    with pytest.raises(FinancePostingError, match="wholly unpaid"):
        act(runtime, order, "prepare-collection", "maker", {"tranche_id": order["lines"][0]["tranches"][0]["id"],
            "receipt_number": "INVALID-FULL", "receipt_date": "2026-10-10", "period_id": "period", "journal_code": "CASH", "cash_account_code": "CASH"})


def test_parallel_lost_ack_post_has_one_receipt_and_effect(receipt_database: tuple[str, str]) -> None:
    runtime = create_stock_runtime(receipt_database)
    _, invoice_id = invoiced(runtime)
    plan = phase(runtime, prepare(runtime, invoice_id, 10000), "review", "checker", "review")
    with ThreadPoolExecutor(max_workers=3) as executor:
        results = list(executor.map(lambda _: phase(runtime, plan, "post", "poster", "lost-ack-post"), range(3)))
    assert results[0] == results[1] == results[2]
    with runtime.actor("poster") as (connection, _, _actor):
        assert connection.execute("SELECT count(*) n FROM reconforge.commercial_collection_links WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 1
        assert connection.execute("SELECT count(*) n FROM reconforge.ar_receipts WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 1


def test_sql_unowned_receipt_allocation_and_plan_mutation_are_rejected(receipt_database: tuple[str, str]) -> None:
    import psycopg

    from reconforge.application.receivables import ReceiptAllocationInput
    from reconforge.infrastructure.postgres_receivables import PostgresReceivablesRepository
    runtime = create_stock_runtime(receipt_database)
    _, invoice_id = invoiced(runtime)
    posted = complete(runtime, prepare(runtime, invoice_id, 10000), "first")
    with pytest.raises(psycopg.errors.CheckViolation), runtime.actor("poster") as (connection, _, actor):
        PostgresReceivablesRepository(connection, runtime.tenant).post_receipt(receipt_number="UNOWNED", customer_code="CUSTOMER",
            receipt_date="2026-10-10", currency_code="USD", amount_minor=1000, workspace="work", organization_code="ORG", entity_code="ENTITY",
            allocations=[ReceiptAllocationInput(invoice_id=invoice_id, amount_minor=1000)], actor_label=actor.username)
    with pytest.raises(psycopg.errors.CheckViolation, match="immutable"), runtime.actor("maker") as (connection, _, _actor):
        connection.execute("UPDATE reconforge.commercial_collection_plans SET amount_minor=1 WHERE tenant_id=%s AND id=%s", (runtime.tenant, posted["id"]))
    with runtime.actor("poster") as (connection, _, actor):
        assert PostgresCommercialCollectionsRepository(connection, runtime.tenant).get(posted["id"], actor=actor) == posted
