"""Actual scoped HTTP FX lifecycle over restricted PostgreSQL and human identity."""

from dataclasses import asdict
from pathlib import Path
from typing import Any

from reconforge.api.routes.operational_fx_tax import router
from tests.test_postgres_inventory_receipt_posting import ReceiptRuntime
from tests.test_postgres_operational_finance_api import client_for
from tests.test_postgres_operational_fx_tax import fx_request, fx_runtime, pytestmark, receipt_database

__all__ = ["fx_runtime", "pytestmark", "receipt_database"]


def invoice_body() -> dict[str, Any]:
    body = asdict(fx_request())
    for field in ("workspace_id", "organization_id", "legal_entity_id", "organization_code", "entity_code"):
        del body[field]
    body["net_minor"] = str(body["net_minor"])
    body["taxes"] = list(body["taxes"])
    return {"command_id": "api-invoice", **body}


def install_owned_router(client: Any) -> None:
    # Global app registration belongs to the integrating owner. This fixture
    # exercises the exact router on the normal app's middleware/identity stack.
    client.app.include_router(router, prefix="/api/v1")


def test_actual_http_foreign_invoice_tax_partial_settlement_and_three_humans(
    fx_runtime: ReceiptRuntime, receipt_database: tuple[str, str], tmp_path: Path,
) -> None:
    runtime = fx_runtime
    with client_for(runtime, receipt_database, tmp_path, "maker") as (client, headers):
        install_owned_router(client)
        response = client.post("/api/v1/operational-fx-tax/invoices", headers=headers, json=invoice_body())
        assert response.status_code == 200, response.text
        plan = response.json()["plan"]
        assert plan["amount_minor"] == "14251"
        same = client.post("/api/v1/operational-fx-tax/invoices", headers=headers, json=invoice_body())
        assert same.status_code == 200 and same.json()["plan"] == plan
        self_review = client.post(f"/api/v1/operational-fx-tax/plans/{plan['id']}/review", headers=headers,
            json={"command_id": "self-review", "expected_plan_digest": plan["plan_digest"], "reason": "Self review"})
        assert self_review.status_code == 403, self_review.text
    for name, operation in (("checker", "review"), ("poster", "post")):
        with client_for(runtime, receipt_database, tmp_path, name) as (client, headers):
            install_owned_router(client)
            response = client.post(f"/api/v1/operational-fx-tax/plans/{plan['id']}/{operation}", headers=headers,
                json={"command_id": "api-" + operation, "expected_plan_digest": plan["plan_digest"], "reason": "Independent " + operation})
            assert response.status_code == 200, response.text
            plan = response.json()["plan"]
    with client_for(runtime, receipt_database, tmp_path, "maker") as (client, headers):
        install_owned_router(client)
        response = client.post(f"/api/v1/operational-fx-tax/invoices/{plan['source_id']}/settlements", headers=headers, json={"command_id": "api-settle",
            "foreign_minor": "4000", "settlement_rate": {"rate": "1.3", "source": "Synthetic current spot", "effective_at": "2026-10-02T12:00:00Z"},
            "period_id": "period", "posting_date": "2026-10-02", "reason": "Foreign partial receipt"})
        assert response.status_code == 200, response.text
        partial = response.json()["plan"]
        assert partial["equation"]["realized_fx_minor"] == "200"
    for name, operation in (("checker", "review"), ("poster", "post")):
        with client_for(runtime, receipt_database, tmp_path, name) as (client, headers):
            install_owned_router(client)
            response = client.post(f"/api/v1/operational-fx-tax/plans/{partial['id']}/{operation}", headers=headers,
                json={"command_id": "api-settle-" + operation, "expected_plan_digest": partial["plan_digest"], "reason": "Independent partial " + operation})
            assert response.status_code == 200, response.text
    with client_for(runtime, receipt_database, tmp_path, "poster", step_up=False) as (client, headers):
        install_owned_router(client)
        response = client.get(f"/api/v1/operational-fx-tax/invoices/{plan['source_id']}", headers=headers)
        assert response.status_code == 200, response.text
        detail = response.json()["invoice"]
        assert detail["foreign_outstanding_minor"] == "7401" and detail["functional_outstanding_minor"] == "9251"
        assert detail["foreign_policy"]["currency_code"] == "EUR" and detail["functional_policy"]["currency_code"] == "USD"
        evidence = client.get(f"/api/v1/operational-fx-tax/plans/{partial['id']}/evidence", headers=headers)
        assert evidence.status_code == 200 and len(evidence.json()["evidence"]["phases"]) == 4
        denied = client.get(f"/api/v1/operational-fx-tax/invoices/{plan['source_id']}", headers={**headers, "X-ReconForge-Legal-Entity": "foreign"})
        assert denied.status_code in {403, 404} and "source_digest" not in denied.text


def test_http_fx_strict_money_policy_and_unknown_fields_are_rejected_without_effects(
    fx_runtime: ReceiptRuntime, receipt_database: tuple[str, str], tmp_path: Path,
) -> None:
    with client_for(fx_runtime, receipt_database, tmp_path, "maker") as (client, headers):
        install_owned_router(client)
        for changes in ({"net_minor": 10001}, {"net_minor": "100.01"}, {"unexpected": True}, {"net_minor": "9000000000000000001"},
                        {"original_rate": {"rate": 1.25, "source": "Synthetic", "effective_at": "2026-10-01T12:00:00Z"}}):
            response = client.post("/api/v1/operational-fx-tax/invoices", headers=headers, json={**invoice_body(), **changes})
            assert response.status_code in {400, 422}, response.text
        wrong = invoice_body()
        wrong["taxes"][0]["country_code"] = "US"
        response = client.post("/api/v1/operational-fx-tax/invoices", headers=headers, json=wrong)
        assert response.status_code == 400 and response.json()["error"]["code"] == "fx_tax_policy_invalid"
        current = client.get("/api/v1/operational-fx-tax/invoices", headers=headers)
        assert current.status_code == 200 and current.json()["invoices"] == []
