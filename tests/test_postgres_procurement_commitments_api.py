"""Authenticated native appropriation-backed PO and current-assurance boundary."""
from contextlib import ExitStack
from dataclasses import asdict
from pathlib import Path
from typing import Any

from reconforge.api.routes.procurement_commitments import router
from tests.test_postgres_procurement_commitments import budget_runtime, receipt_database
from tests.test_postgres_procurement_partial import CHECKER, MAKER, POSTER
from tests.test_postgres_procurement_partial_api import ROOT, owner_action, partial_client, post
from tests.test_procurement_multiline import enterprise_request

__all__ = ["budget_runtime", "receipt_database"]
COMMITMENTS = "/api/v1/procurement-commitments/orders"


def test_authenticated_native_budget_purchase_receiving_ap_consumption_and_release(budget_runtime: tuple[Any, dict[str, Any]], receipt_database: tuple[str, str], tmp_path: Path) -> None:
    runtime, budget = budget_runtime
    with ExitStack() as stack:
        clients = [stack.enter_context(partial_client(runtime, receipt_database, tmp_path / name, name)) for name in (MAKER, CHECKER, POSTER)]
        # Registration belongs to the integration owner. This fixture installs
        # the real router on the actual authenticated app while it is isolated.
        for client, _ in clients:
            if not any(getattr(route, "path", "") == COMMITMENTS for route in client.app.routes):
                client.app.include_router(router, prefix="/api/v1")
        maker, checker, poster = clients
        source = asdict(enterprise_request("BPC1-HTTP"))
        source["lines"] = [{**line, "unit_price_minor": str(line["unit_price_minor"])} for line in source["lines"]]
        payload = {**source, "budget_id": budget["id"], "expected_budget_version": budget["row_version"], "reason": "Reserve exact approved native merchandise", "command_id": "http-budget-po"}
        invalid = maker[0].post(COMMITMENTS, headers=maker[1], json={**payload, "expected_budget_version": True})
        assert invalid.status_code == 422
        owner = post(maker, COMMITMENTS, payload)
        assert (owner["original_minor"], owner["remaining_minor"]) == ("17000", "17000")
        path = COMMITMENTS + "/" + owner["order_id"]
        wrong_scope = maker[0].get(path, headers={**maker[1], "X-ReconForge-Legal-Entity": "foreign"})
        assert wrong_scope.status_code == 403
        view = maker[0].get(ROOT + "/orders/" + owner["order_id"], headers=maker[1]).json()
        view = owner_action(checker, owner_action(maker, view, "submit-order"), "approve-order")
        for index, quantity in ((0, "2"), (1, "2.50")):
            view = owner_action(maker, view, "prepare-receipt-line", line_id=view["lines"][index]["id"], quantity=quantity, posting_date="2026-10-03", period_id="period")
            receipt = view["receipts"][-1]["id"]
            view = owner_action(poster, owner_action(checker, view, "review-receipt", receipt), "receive", receipt)
        view = owner_action(maker, view, "match-invoice-lines", posting_date="2026-10-03", period_id="period",
            lines=[{"line_id": view["lines"][index]["id"], "quantity": quantity} for index, quantity in ((0, "2"), (1, "2.50"))])
        invoice = view["invoices"][-1]["id"]
        for action, client in (("approve-invoice", checker), ("prepare-accrual", maker), ("review-accrual", checker)):
            view = owner_action(client, view, action, invoice)
        detached = poster[0].post(ROOT + "/orders/" + owner["order_id"] + "/commands/post-accrual", headers=poster[1],
            json={"command_id": "detached-budget-post", "expected_version": view["order"]["row_version"], "document_id": invoice, "reason": "Bypass budget owner"})
        assert detached.status_code == 403 and detached.json()["error"]["code"] == "procurement_commitment_owner_required"
        owner = post(poster, path + "/consume", {"command_id": "http-budget-consume", "invoice_id": invoice,
            "expected_order_version": view["order"]["row_version"], "expected_budget_version": owner["budget_version"], "reason": "Same exact AP accrual and appropriation consumption"})
        assert (owner["consumed_minor"], owner["remaining_minor"]) == ("7400", "9600")
        view = maker[0].get(ROOT + "/orders/" + owner["order_id"], headers=maker[1]).json()
        owner = post(checker, path + "/release", {"command_id": "http-budget-release", "expected_order_version": view["order"]["row_version"],
            "expected_budget_version": owner["budget_version"], "posting_date": "2026-10-04", "reason": "Release independently approved unreceived remainder"})
        assert owner["status"] == "Released" and owner["released_minor"] == "9600"
        assert maker[0].get(path, headers=maker[1]).json() == owner


def test_api_budget_purchase_requires_fresh_human_step_up(budget_runtime: tuple[Any, dict[str, Any]], receipt_database: tuple[str, str], tmp_path: Path) -> None:
    runtime, budget = budget_runtime
    with partial_client(runtime, receipt_database, tmp_path, MAKER, step_up=False) as client:
        if not any(getattr(route, "path", "") == COMMITMENTS for route in client[0].app.routes):
            client[0].app.include_router(router, prefix="/api/v1")
        source = asdict(enterprise_request("BPC1-NO-ASSURANCE"))
        source["lines"] = [{**line, "unit_price_minor": str(line["unit_price_minor"])} for line in source["lines"]]
        response = client[0].post(COMMITMENTS, headers=client[1], json={**source, "budget_id": budget["id"], "expected_budget_version": budget["row_version"], "command_id": "unassured-reserve", "reason": "Missing live privileged assurance"})
        assert response.status_code == 403
        with runtime.actor(CHECKER) as (connection, _, _):
            assert connection.execute("SELECT count(*) FROM reconforge.procurement_commitment_plans WHERE tenant_id=%s", (runtime.tenant,)).fetchone()[0] == 0
