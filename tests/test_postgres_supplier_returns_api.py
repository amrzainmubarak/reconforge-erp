"""Authenticated original supplier debit with live assurance and canonical scopes."""
from contextlib import ExitStack
from dataclasses import asdict
from pathlib import Path

from reconforge.api.routes.supplier_returns import router
from tests.test_postgres_inventory_receipt_posting import ReceiptRuntime
from tests.test_postgres_procurement_partial_api import partial_client, post
from tests.test_postgres_supplier_returns import CHECKER, MAKER, POSTER, preparation, receipt_database, runtime, source

__all__ = ["receipt_database", "runtime"]
ROOT = "/api/v1/supplier-returns"


def register(client: object) -> None:
    app = client.app
    if not any(getattr(route, "path", "") == ROOT + "/plans" for route in app.routes):
        app.include_router(router, prefix="/api/v1")


def test_authenticated_exact_original_supplier_credit_and_live_replay(runtime: ReceiptRuntime, receipt_database: tuple[str, str], tmp_path: Path) -> None:
    purchase = source(runtime)
    with ExitStack() as stack:
        maker, checker, poster = [stack.enter_context(partial_client(runtime, receipt_database, tmp_path / name, name)) for name in (MAKER, CHECKER, POSTER)]
        for client, _ in (maker, checker, poster):
            register(client)
        payload = {**asdict(preparation(purchase)), "command_id": "http-sr-prepare"}
        invalid = maker[0].post(ROOT + "/plans", headers=maker[1], json={**payload, "receipt_id": True})
        assert invalid.status_code == 422
        plan = post(maker, ROOT + "/plans", payload)
        assert post(maker, ROOT + "/plans", payload) == plan
        assert maker[0].get(ROOT + "/plans/" + plan["id"], headers={**maker[1], "X-ReconForge-Legal-Entity": "foreign"}).status_code == 403
        denied = maker[0].post(ROOT + "/plans/" + plan["id"] + "/review", headers=maker[1], json={"command_id": "self-review", "expected_plan_digest": plan["plan_digest"], "reason": "Self review refused"})
        assert denied.status_code == 403
        for operation, client in (("review", checker), ("post", poster)):
            phase_payload = {"command_id": "http-sr-" + operation, "expected_plan_digest": plan["plan_digest"], "reason": "Independent original native supplier debit"}
            plan = post(client, ROOT + "/plans/" + plan["id"] + "/" + operation, phase_payload)
            assert post(client, ROOT + "/plans/" + plan["id"] + "/" + operation, phase_payload) == plan
        assert (plan["status"], plan["credit_minor"], plan["inventory_removed_minor"], len(plan["posting_effect_ids"])) == ("Posted", "2400", "2400", 2)
        assert maker[0].get(ROOT + "/plans/" + plan["id"], headers=maker[1]).json() == plan
        assert maker[0].get(ROOT + "/orders/" + purchase["order"]["id"], headers=maker[1]).json() == {"records": [plan]}


def test_supplier_debit_requires_current_live_human_assurance(runtime: ReceiptRuntime, receipt_database: tuple[str, str], tmp_path: Path) -> None:
    purchase = source(runtime)
    with partial_client(runtime, receipt_database, tmp_path, MAKER, step_up=False) as maker:
        register(maker[0])
        response = maker[0].post(ROOT + "/plans", headers=maker[1], json={**asdict(preparation(purchase)), "command_id": "unassured-supplier-return"})
        assert response.status_code == 403
    with runtime.actor(CHECKER) as (connection, _, _):
        assert connection.execute("SELECT count(*) AS count FROM reconforge.supplier_return_plans WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["count"] == 0
