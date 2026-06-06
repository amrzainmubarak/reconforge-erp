from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.audit import list_audit_events
from reconforge.auth import LocalAuthService
from reconforge.db import connect, run_migrations


def _setup(tmp_path: Path) -> tuple[TestClient, Path]:
    db_path = tmp_path / "audit_workflow_api.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        auth = LocalAuthService(connection)
        auth.init_admin(username="admin", password="Secret-123")
        auth.create_user(username="preparer", password="Secret-123", role="preparer")
        auth.create_user(username="reviewer", password="Secret-123", role="reviewer")
    finally:
        connection.close()
    return TestClient(create_api_app(db_path)), db_path


def _token(client: TestClient, username: str) -> str:
    response = client.post("/api/v1/auth/login", json={"username": username, "password": "Secret-123"})
    assert response.status_code == 200
    return str(response.json()["access_token"])


def test_audit_events_requires_permission_and_verify_works(tmp_path: Path) -> None:
    client, _ = _setup(tmp_path)
    admin_headers = {"Authorization": f"Bearer {_token(client, 'admin')}"}
    preparer_headers = {"Authorization": f"Bearer {_token(client, 'preparer')}"}

    denied = client.get("/api/v1/audit/events", headers=preparer_headers)
    events = client.get("/api/v1/audit/events", headers=admin_headers)
    verify = client.get("/api/v1/audit/verify", headers=admin_headers)

    assert denied.status_code == 403
    assert events.status_code == 200
    assert events.json()["events"]
    assert verify.status_code == 200
    assert verify.json()["ok"] is True
    assert "Traceback" not in denied.text + events.text + verify.text


def test_workflow_transitions_and_transition_route_emit_audit_event(tmp_path: Path) -> None:
    client, db_path = _setup(tmp_path)
    admin_headers = {"Authorization": f"Bearer {_token(client, 'admin')}"}
    preparer_headers = {"Authorization": f"Bearer {_token(client, 'preparer')}"}

    transitions = client.get("/api/v1/workflow/transitions?object_type=reconciliation", headers=admin_headers)
    created = client.post(
        "/api/v1/workflow/objects",
        headers=admin_headers,
        json={"object_type": "reconciliation", "object_id": "REC-API-1", "status": "Draft"},
    )
    transitioned = client.post(
        "/api/v1/workflow/objects/reconciliation/REC-API-1/transition",
        headers=preparer_headers,
        json={"to_status": "Prepared", "reason": "Prepared locally"},
    )
    current = client.get("/api/v1/workflow/objects/reconciliation/REC-API-1", headers=admin_headers)
    history = client.get("/api/v1/workflow/objects/reconciliation/REC-API-1/history", headers=admin_headers)

    connection = connect(db_path, require_exists=True)
    try:
        audit_actions = [event.action for event in list_audit_events(connection)]
    finally:
        connection.close()

    assert transitions.status_code == 200
    assert any(transition["to_status"] == "Prepared" for transition in transitions.json()["transitions"])
    assert created.status_code == 200
    assert transitioned.status_code == 200
    assert transitioned.json()["object"]["status"] == "Prepared"
    assert current.json()["object"]["status"] == "Prepared"
    assert history.status_code == 200
    assert history.json()["history"][0]["actor_label"] == "preparer"
    assert "workflow_transition" in audit_actions


def test_workflow_transition_denies_missing_permission_with_structured_error(tmp_path: Path) -> None:
    client, _ = _setup(tmp_path)
    admin_headers = {"Authorization": f"Bearer {_token(client, 'admin')}"}
    reviewer_headers = {"Authorization": f"Bearer {_token(client, 'reviewer')}"}
    client.post(
        "/api/v1/workflow/objects",
        headers=admin_headers,
        json={"object_type": "reconciliation", "object_id": "REC-API-2", "status": "Draft"},
    )

    denied = client.post(
        "/api/v1/workflow/objects/reconciliation/REC-API-2/transition",
        headers=reviewer_headers,
        json={"to_status": "Prepared"},
    )

    assert denied.status_code == 400
    payload = denied.json()
    assert payload["error"]["code"] == "workflow_transition_failed"
    assert "Traceback" not in denied.text
