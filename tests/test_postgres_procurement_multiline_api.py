"""Real HTTP multiline purchasing and native payable settlement under RLS."""
from contextlib import ExitStack
from dataclasses import asdict
from pathlib import Path

import pytest

from tests.test_postgres_procurement_multiline import (
    CHECKER,
    MAKER,
    POSTER,
    create_multiline_runtime,
    enterprise_digest,
    pytestmark,
    receipt_database,
)
from tests.test_postgres_procurement_partial_api import INSTALLMENTS, ROOT, owner_action, partial_client, post
from tests.test_procurement_multiline import enterprise_request

__all__ = ["pytestmark", "receipt_database"]


def test_authenticated_multiline_receiving_invoice_partial_payment_and_scoped_pages(
    receipt_database: tuple[str, str], tmp_path: Path,
) -> None:
    runtime = create_multiline_runtime(receipt_database)
    with ExitStack() as stack:
        maker, checker, poster = [stack.enter_context(partial_client(runtime, receipt_database, tmp_path / actor, actor))
                                 for actor in (MAKER, CHECKER, POSTER)]
        prepared = asdict(enterprise_request("HTTP-MULTI"))
        prepared["lines"] = [{**line, "unit_price_minor": str(line["unit_price_minor"])} for line in prepared["lines"]]
        prepared["command_id"] = "http-multiline-create"
        view = post(maker, ROOT + "/orders/multiline", prepared)
        assert view["order"]["total_minor"] == "17000" and len(view["lines"]) == 2
        view = owner_action(checker, owner_action(maker, view, "submit-order"), "approve-order")
        for index, quantity in ((0, "4"), (1, "1.25")):
            view = owner_action(maker, view, "prepare-receipt-line", line_id=view["lines"][index]["id"],
                quantity=quantity, posting_date="2026-10-03", period_id="period")
            identifier = view["receipts"][-1]["id"]
            view = owner_action(poster, owner_action(checker, view, "review-receipt", identifier), "receive", identifier)
        view = owner_action(maker, view, "match-invoice-lines", posting_date="2026-10-03", period_id="period",
            lines=[{"line_id": view["lines"][0]["id"], "quantity": "3"}, {"line_id": view["lines"][1]["id"], "quantity": "1"}])
        invoice = view["invoices"][0]
        assert invoice["quantity_text"] is None and invoice["total_minor"] == "5600" and len(invoice["lines"]) == 2
        for operation, client in (("approve-invoice", checker), ("prepare-accrual", maker), ("review-accrual", checker), ("post-accrual", poster)):
            view = owner_action(client, view, operation, invoice["id"])
        for index, amount in enumerate(("2000", "3600")):
            plan = post(maker, INSTALLMENTS, {"command_id": "http-payment-" + str(index), "source_id": invoice["native_invoice_id"],
                "source_kind": "APPayment", "amount_minor": amount, "journal_code": "STOCK", "period_id": "period",
                "posting_date": "2026-10-03", "debit_account_code": "AP", "credit_account_code": "CASH", "reason": "Exact multi-line supplier settlement"})["plan"]
            for phase, client in (("review", checker), ("post", poster)):
                plan = post(client, INSTALLMENTS + "/" + plan["id"] + "/" + phase, {"command_id": "http-" + phase + "-" + str(index),
                    "expected_plan_digest": plan["plan_digest"], "reason": "Independent supplier settlement publication"})["plan"]
            assert plan["posting_effect_id"] and plan["payment_link_id"]
        for path in ("/orders/page", "/orders/" + view["order"]["id"] + "/documents", "/catalog/items?search=WEIGHT",
                     "/orders/" + view["order"]["id"] + "/invoices/" + invoice["id"] + "/payments"):
            read = maker[0].get(ROOT + path, headers=maker[1])
            assert read.status_code == 200, read.text
            if path.endswith("/payments"):
                assert len(read.json()["records"]) == 2 and {record["amount_minor"] for record in read.json()["records"]} == {"2000", "3600"}
            if path.endswith("/documents"):
                assert read.json()["totals"]["paid_minor"] == "5600" and read.json()["invoices"][0]["native_status"] == "Paid"
        denied = maker[0].get(ROOT + "/orders/" + view["order"]["id"] + "/documents",
            headers={**maker[1], "X-ReconForge-Legal-Entity": "foreign-entity"})
        assert denied.status_code == 403, denied.text
        invalid = maker[0].post(ROOT + "/orders/multiline", headers=maker[1], json={**prepared,
            "command_id": "invalid-float", "lines": [{**prepared["lines"][0], "unit_price_minor": 1200.0}]})
        assert invalid.status_code == 422, invalid.text


def test_multiline_http_receiving_late_failure_has_no_partial_source_or_effect(
    receipt_database: tuple[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from reconforge.infrastructure.postgres_procurement_partial import PostgresProcurementPartialRepository
    from tests.test_postgres_procurement_multiline import action, create_order, prepare_line
    runtime = create_multiline_runtime(receipt_database)
    view = prepare_line(runtime, create_order(runtime, "HTTP-ROLLBACK"), 0, "4")
    view = action(runtime, view, "review-receipt", CHECKER, view["receipts"][0]["id"])
    with runtime.actor(MAKER) as (connection, _, _):
        before = enterprise_digest(connection, runtime.tenant)
    original = PostgresProcurementPartialRepository._remember
    def fail_after_ack(self: PostgresProcurementPartialRepository, *args: object, **kwargs: object) -> None:
        original(self, *args, **kwargs)
        raise RuntimeError("Injected real source and financial acknowledgement failure")
    with partial_client(runtime, receipt_database, tmp_path, POSTER) as client:
        monkeypatch.setattr(PostgresProcurementPartialRepository, "_remember", fail_after_ack)
        with pytest.raises(RuntimeError, match="real source and financial"):
            owner_action(client, view, "receive", view["receipts"][0]["id"])
        monkeypatch.setattr(PostgresProcurementPartialRepository, "_remember", original)
        with runtime.actor(MAKER) as (connection, _, _):
            assert enterprise_digest(connection, runtime.tenant) == before
        result = owner_action(client, view, "receive", view["receipts"][0]["id"])
        assert result["receipts"][0]["stage"] == "Posted" and result["totals"]["received_minor"] == "4800"
