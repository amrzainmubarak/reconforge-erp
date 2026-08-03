from pathlib import Path

from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.auth.service import LocalAuthService
from reconforge.db import connect, run_migrations
from tests.test_connector_writeback import _intent


def test_writeback_intent_api_is_authenticated_actor_bound_and_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "connector-api.db"
    run_migrations(db_path)
    connection = connect(db_path)
    admin = LocalAuthService(connection).init_admin(username="admin", password="Secret-123")
    LocalAuthService(connection).create_user(username="controller", password="Secret-123", role="controller")
    connection.close()
    client = TestClient(create_api_app(db_path))

    payload = _intent().model_copy(update={"requested_by": admin.id}).model_dump(mode="json")
    assert client.post("/api/v1/connectors/writeback/intents", json=payload).status_code == 401
    login = client.post("/api/v1/auth/login", json={"username": "admin", "password": "Secret-123"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    first = client.post("/api/v1/connectors/writeback/intents", json=payload, headers=headers)
    second = client.post("/api/v1/connectors/writeback/intents", json=payload, headers=headers)
    assert first.status_code == second.status_code == 200, (first.text, second.text)
    assert first.json()["version"] == second.json()["version"] == 1
    assert first.json()["network_dispatch"] == "disabled"
    assert first.json()["digest"] == second.json()["digest"]

    controller_login = client.post(
        "/api/v1/auth/login", json={"username": "controller", "password": "Secret-123"}
    )
    controller_headers = {"Authorization": f"Bearer {controller_login.json()['access_token']}"}
    approval = client.post(
        f"/api/v1/connectors/writeback/intents/{payload['intent_id']}/approve",
        json={"assurance": "mfa", "reason": "independent review", "tenant_id": "tenant-a", "workspace_id": "workspace-a"},
        headers=controller_headers,
    )
    assert approval.status_code == 200, approval.text
    assert approval.json()["version"] == 2
    assert approval.json()["intent"]["status"] == "approved"
    assert approval.json()["network_dispatch"] == "disabled"
    repeated = client.post(
        f"/api/v1/connectors/writeback/intents/{payload['intent_id']}/approve",
        json={"assurance": "mfa", "reason": "repeat", "tenant_id": "tenant-a", "workspace_id": "workspace-a"},
        headers=controller_headers,
    )
    assert repeated.status_code == 409

    mismatched = {**payload, "requested_by": "different-actor"}
    denied = client.post("/api/v1/connectors/writeback/intents", json=mismatched, headers=headers)
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "writeback_actor_mismatch"

    check = connect(db_path)
    try:
        assert check.execute("SELECT COUNT(*) FROM connector_writeback_intents").fetchone()[0] == 2
    finally:
        check.close()
