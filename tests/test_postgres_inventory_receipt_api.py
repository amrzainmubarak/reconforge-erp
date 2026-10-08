"""Password-authenticated HTTPS receipt/FIFO/GL commands over the real restricted role."""
import json
from pathlib import Path

from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.api.routes.inventory_receipt_posting import router
from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_scope_authority import PostgresScopeAuthorityRepository
from tests.test_postgres_inventory_receipt_posting import receipt_database, receipt_runtime

__all__ = ["receipt_database", "receipt_runtime"]

def test_live_http_review_commit_recovery_full_inverse_and_denials(receipt_runtime, tmp_path: Path):
    import psycopg
    runtime = receipt_runtime
    with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant) as connection:
        grants = PostgresScopeAuthorityRepository(connection)
        for username in ("maker", "checker", "poster"):
            for kind, identifier in (("workspace", "work"), ("organization", "org"), ("legal_entity", "entity")):
                grants.grant(tenant_id=runtime.tenant, grant_id=f"{username}-{identifier}", principal_type="user", principal_id=username, scope_type=kind, scope_id=identifier, actor_id=username)
    app = create_api_app(tmp_path / "unused.db", tenant_db_root=tmp_path / "tenants", postgres_dsn=runtime.factory.settings.dsn, postgres_require_tls=False, secure_transport=True)
    app.include_router(router, prefix="/api/v1")
    scope = {"X-ReconForge-Tenant": runtime.tenant, "X-ReconForge-Workspace": "work", "X-ReconForge-Organization": "org", "X-ReconForge-Legal-Entity": "entity"}
    with TestClient(app, base_url="https://testserver") as client:
        identities = {}
        for name in ("maker", "checker"):
            response = client.post("/api/v1/auth/login", headers=scope, json={"username": name, "password": runtime.password})
            assert response.status_code == 200, response.text
            identities[name] = {**scope, "Authorization": "Bearer " + response.json()["access_token"]}
        maker, checker = identities["maker"], identities["checker"]
        body = dict(command_id="http-prepare", receipt_number="HTTP-REC", posting_date="2026-10-03", period_id="period", item_code="ITEM", location_code="MAIN/STOCK", quantity="10", total_value_minor="12000", policy_code="FIFO", organization_code="ORG", entity_code="ENTITY", workspace="work", reason="Actual exact stock source")
        endpoint = "/api/v1/inventory-receipt-posting/plans"
        assert client.post(endpoint, headers=maker, json=body).status_code == 403
        for headers in (maker, checker):
            assert client.post("/api/v1/auth/step-up", headers=headers, json={"password": runtime.password}).status_code == 200
        prepared = client.post(endpoint, headers=maker, json=body)
        assert prepared.status_code == 200, prepared.text
        plan = prepared.json()["receipt"]
        uri = endpoint + "/" + plan["plan_id"]
        assert plan["status"] == "Prepared" and plan["total_value_minor"] == "12000"
        review_body = {"command_id": "http-review", "expected_plan_digest": plan["plan_digest"], "reason": "Independent actual review"}
        assert client.post(uri + "/review", headers=maker, json=review_body).status_code == 403
        assert client.post(uri + "/review", headers=checker, json={**review_body, "expected_plan_digest": "0" * 64}).status_code == 400
        reviewed = client.post(uri + "/review", headers=checker, json=review_body)
        assert reviewed.status_code == 200, reviewed.text
        review = reviewed.json()["receipt"]
        commit_body = {"command_id": "http-commit", "expected_review_digest": review["review_digest"], "reason": "Complete reviewed stock and GL"}
        posted = client.post(uri + "/commit", headers=checker, json=commit_body)
        assert posted.status_code == 200, posted.text
        effect = posted.json()["receipt"]
        assert effect["status"] == "Committed"
        assert json.loads(effect["effect_json"])["finance_effect"]["snapshot"]["lines"][0]["debit_minor"] == 12000
        assert client.post(uri + "/commit", headers=checker, json=commit_body).json() == posted.json()
        assert client.post(uri + "/commit", headers=checker, json={**commit_body, "reason": "Changed retry"}).status_code == 409
        # Preparation recovery is authoritative even after another human completed the source.
        assert client.post(endpoint, headers=maker, json=body).json() == posted.json()
        assert client.get(uri, headers={**checker, "X-ReconForge-Workspace": "sibling"}).status_code == 403
        inverse = client.post(uri + "/reversal", headers=maker, json={"command_id": "http-inverse", "reversal_number": "HTTP-RETURN", "posting_date": "2026-10-04", "period_id": "period", "reason": "Return entire unused source"})
        assert inverse.status_code == 200, inverse.text
        inverse_plan = inverse.json()["receipt"]
        inverse_uri = endpoint + "/" + inverse_plan["plan_id"]
        reviewed = client.post(inverse_uri + "/review", headers=checker, json={"command_id": "inverse-review", "expected_plan_digest": inverse_plan["plan_digest"], "reason": "Unused original checked"})
        assert reviewed.status_code == 200, reviewed.text
        reverted = client.post(inverse_uri + "/commit", headers=checker, json={"command_id": "inverse-commit", "expected_review_digest": reviewed.json()["receipt"]["review_digest"], "reason": "Complete unused inverse"})
        assert reverted.status_code == 200, reverted.text
        assert client.get(uri, headers=checker).json() == posted.json()
        # Browser mutations enforce the actual cookie/session CSRF boundary.
        browser = client.post("/api/v1/auth/browser/login", headers=scope, json={"username": "checker", "password": runtime.password})
        assert browser.status_code == 200, browser.text
        assert client.post(uri + "/commit", headers=scope, json=commit_body).status_code == 403
        browser_headers = {**scope, "X-ReconForge-CSRF": browser.json()["csrf_token"]}
        assert client.post("/api/v1/auth/step-up", headers=browser_headers, json={"password": runtime.password}).status_code == 200
        assert client.post(uri + "/commit", headers=browser_headers, json=commit_body).json() == posted.json()
    with psycopg.connect(runtime.admin_dsn) as admin:
        layer = admin.execute("SELECT remaining_quantity_scaled,remaining_value_minor FROM reconforge.inventory_cost_layers WHERE tenant_id=%s AND id=%s", (runtime.tenant, effect["cost_layer_id"])).fetchone()
        assert layer == (0, 0)
        assert admin.execute("SELECT count(*) FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (runtime.tenant,)).fetchone()[0] == 2
