"""Registered PB1 HTTP contract over native AR/GL; HTTPS scheme is not socket TLS."""

from pathlib import Path

from fastapi.testclient import TestClient

from tests.test_postgres_people_project_payroll_api import application, sessions
from tests.test_postgres_project_time_billing import PeopleRuntime, approved_time

pytest_plugins = ("tests.test_postgres_project_time_billing",)
ROOT = "/api/v1/project-time-billing"


def test_registered_http_price_time_native_ar_partial_final_cash_and_original_evidence(billing: PeopleRuntime, tmp_path: Path) -> None:
    times = approved_time(billing)
    # Billing uses the ordinary finance factory; private wages are not queried.
    app = application(billing, tmp_path, private=False)
    assert ROOT + "/invoices" in app.openapi()["paths"]
    with TestClient(app, base_url="https://testserver") as client:
        headers = sessions(client, billing)
        projects = client.get("/api/v1/people-project-payroll/catalog/projects?limit=100", headers=headers["maker"])
        assert projects.status_code == 200, projects.text
        prices = []
        for project in projects.json()["items"]:
            response = client.post(ROOT + "/prices", headers=headers["maker"], json={"command_id": "http-price-" + project["id"],
                "customer_code": "CUSTOMER", "project_id": project["id"], "valid_from": "2026-10-01", "valid_through": "2026-10-31",
                "currency_code": "USD", "hourly_price_minor": "2001" if project["project_code"] == "P1" else "3001", "reason": "Synthetic service price"})
            assert response.status_code == 200, response.text
            price = response.json()["price"]
            body = {"command_id": "http-price-review-" + price["id"], "expected_digest": price["source_digest"]}
            assert client.post(ROOT + "/prices/" + price["id"] + "/approve", headers=headers["maker"], json=body).status_code == 409
            response = client.post(ROOT + "/prices/" + price["id"] + "/approve", headers=headers["checker"], json=body)
            assert response.status_code == 200, response.text
            prices.append(price["id"])
        body = {"command_id": "http-bill", "time_ids": times, "price_ids": prices, "customer_code": "CUSTOMER", "invoice_number": "HTTP-PROJECT",
                "period_id": "period", "posting_date": "2026-10-04", "due_date": "2026-10-15", "journal_code": "STOCK",
                "receivable_account_code": "AR", "revenue_account_code": "REVENUE", "cash_account_code": "CASH"}
        response = client.post(ROOT + "/invoices", headers=headers["maker"], json=body)
        assert response.status_code == 200, response.text
        invoice = response.json()["plan"]
        assert invoice["amount_minor"] == "6236"
        def publish(plan: dict, suffix: str) -> None:
            phase = {"command_id": "http-review-" + suffix, "expected_plan_digest": plan["plan_digest"]}
            assert client.post(ROOT + "/plans/" + plan["id"] + "/review", headers=headers["maker"], json=phase).status_code == 409
            reviewed = client.post(ROOT + "/plans/" + plan["id"] + "/review", headers=headers["checker"], json=phase)
            assert reviewed.status_code == 200, reviewed.text
            phase["command_id"] = "http-post-" + suffix
            assert client.post(ROOT + "/plans/" + plan["id"] + "/post", headers=headers["checker"], json=phase).status_code == 409
            posted = client.post(ROOT + "/plans/" + plan["id"] + "/post", headers=headers["poster"], json=phase)
            assert posted.status_code == 200, posted.text
            assert client.post(ROOT + "/plans/" + plan["id"] + "/post", headers=headers["poster"], json=phase).json() == posted.json()
        publish(invoice, "invoice")
        for suffix, amount in (("partial", "1000"), ("final", "5236")):
            response = client.post(ROOT + "/invoices/" + invoice["id"] + "/collections", headers=headers["maker"],
                json={"command_id": "http-" + suffix, "amount_minor": amount, "period_id": "period", "posting_date": "2026-10-05"})
            assert response.status_code == 200, response.text
            publish(response.json()["plan"], suffix)
        result = client.get(ROOT + "/invoices/" + invoice["id"] + "/evidence", headers=headers["maker"])
        assert result.status_code == 200, result.text
        proof = result.json()["evidence"]
        assert len(proof["native_effects"]) == 3 and proof["ar_invoice"]["outstanding_minor"] == "0"
        assert proof["observed_native_balances"] == {"AR": "0", "REVENUE": "-6236", "CASH": "6236"}
        assert not any("private" in table or table in {"hc_rates", "hc_employee_private", "hc_payrun_private"} for table in proof["original_rows"])
        assert client.get(ROOT + "/plans/" + invoice["id"], headers={**headers["maker"], "X-ReconForge-Workspace": "foreign"}).status_code == 403
