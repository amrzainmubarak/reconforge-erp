"""Authenticated API landed cost and native merchandise/AP separation."""
from contextlib import ExitStack
from dataclasses import asdict
from pathlib import Path

from tests.test_postgres_landed_cost import request
from tests.test_postgres_procurement_multiline import (
    CHECKER,
    MAKER,
    POSTER,
    create_multiline_runtime,
    pytestmark,
    receipt_database,
)
from tests.test_postgres_procurement_partial_api import ROOT, owner_action, partial_client, post
from tests.test_procurement_multiline import enterprise_request

__all__ = ["pytestmark", "receipt_database"]
LANDED = "/api/v1/landed-cost"


def test_real_api_landed_bundle_posts_stock_cost_and_cash_atomically(receipt_database: tuple[str, str], tmp_path: Path) -> None:
    runtime = create_multiline_runtime(receipt_database)
    with ExitStack() as stack:
        maker, checker, poster = [stack.enter_context(partial_client(runtime, receipt_database, tmp_path / name, name)) for name in (MAKER, CHECKER, POSTER)]
        source = asdict(enterprise_request("HTTP-LANDED"))
        source["lines"] = [{**line, "unit_price_minor": str(line["unit_price_minor"])} for line in source["lines"]]
        view = post(maker, ROOT + "/orders/multiline", {**source, "command_id": "http-lc-order"})
        view = owner_action(checker, owner_action(maker, view, "submit-order"), "approve-order")
        payload = asdict(request(view, "HTTP-PAID-COST"))
        payload.update(command_id="http-lc-prepare", freight_minor="777", duty_minor="224")
        plan = post(maker, LANDED + "/plans", payload)
        assert plan["amount_minor"] == "1001" and len(plan["allocations"]) == 2
        invalid = maker[0].post(LANDED + "/plans", headers=maker[1], json={**payload, "freight_minor": 777.0})
        assert invalid.status_code == 422
        for operation, client in (("review", checker), ("post", poster)):
            plan = post(client, LANDED + "/plans/" + plan["id"] + "/" + operation,
                {"command_id": "http-lc-" + operation, "expected_plan_digest": plan["plan_digest"], "reason": "Independent paid charge and receiving evidence"})
        assert plan["phase"] == 2 and plan["posting_effect_id"] and all(allocation["stage"] == 2 for allocation in plan["allocations"])
        read = maker[0].get(LANDED + "/orders/" + view["order"]["id"], headers=maker[1])
        assert read.status_code == 200 and read.json() == {"records": [plan], "next_after": None}
        denied = maker[0].get(LANDED + "/plans/" + plan["id"], headers={**maker[1], "X-ReconForge-Legal-Entity": "foreign-entity"})
        assert denied.status_code == 403
        current = maker[0].get(ROOT + "/orders/" + view["order"]["id"], headers=maker[1])
        assert current.status_code == 200 and current.json()["totals"]["received_minor"] == "17000"
        # Goods invoice matching still uses base price after freight capitalization.
        current_view = owner_action(maker, current.json(), "match-invoice-lines", posting_date="2026-10-03", period_id="period",
            lines=[{"line_id": line["id"], "quantity": line["quantity_text"]} for line in current.json()["lines"]])
        assert current_view["invoices"][0]["total_minor"] == "17000" and current_view["invoices"][0]["stage"] == "Matched"
