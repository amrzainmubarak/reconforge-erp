from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.auth import LocalAuthService
from reconforge.db import connect, run_migrations
from reconforge.platform.evidence import EvidenceRegistryService
from reconforge.platform.metrics import MetricsService


def _setup(tmp_path: Path) -> tuple[TestClient, Path]:
    db_path = tmp_path / "api_platform.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        auth = LocalAuthService(connection)
        auth.init_admin(username="admin", password="Secret-123")
        auth.create_user(username="prep", password="Secret-123", role="preparer")
        auth.create_user(username="review", password="Secret-123", role="reviewer")
        MetricsService(connection).compute(actor_label="admin")
    finally:
        connection.close()
    return TestClient(create_api_app(db_path)), db_path


def _token(client: TestClient, username: str) -> str:
    response = client.post("/api/v1/auth/login", json={"username": username, "password": "Secret-123"})
    assert response.status_code == 200
    return str(response.json()["access_token"])


def test_account_api_lifecycle_and_metrics_are_rbac_protected(tmp_path: Path) -> None:
    client, _ = _setup(tmp_path)
    prep_headers = {"Authorization": f"Bearer {_token(client, 'prep')}"}
    review_headers = {"Authorization": f"Bearer {_token(client, 'review')}"}

    created = client.post(
        "/api/v1/accounts/reconciliations",
        headers=prep_headers,
        json={
            "period_name": "2026-05",
            "entity_code": "US01",
            "account_code": "1000",
            "account_name": "Cash",
            "balance": 50,
        },
    )
    reconciliation_id = created.json()["reconciliation"]["id"]
    prepared = client.post(f"/api/v1/accounts/reconciliations/{reconciliation_id}/prepare", headers=prep_headers, json={})
    submitted = client.post(f"/api/v1/accounts/reconciliations/{reconciliation_id}/submit", headers=prep_headers, json={})
    reviewed = client.post(f"/api/v1/accounts/reconciliations/{reconciliation_id}/review", headers=review_headers, json={})
    completed = client.post(f"/api/v1/accounts/reconciliations/{reconciliation_id}/complete", headers=review_headers, json={})
    metrics = client.get("/api/v1/metrics/dashboard", headers=review_headers)
    denied = client.post(f"/api/v1/accounts/reconciliations/{reconciliation_id}/review", headers=prep_headers, json={})

    assert created.status_code == 200
    assert prepared.json()["reconciliation"]["status"] == "Prepared"
    assert submitted.json()["reconciliation"]["status"] == "In Review"
    assert reviewed.json()["reconciliation"]["status"] == "Reviewed"
    assert completed.json()["reconciliation"]["status"] == "Complete"
    assert metrics.status_code == 200
    assert denied.status_code == 403
    assert "Traceback" not in denied.text


def test_local_evidence_cursor_pagination_is_signed_and_offset_compatible(tmp_path: Path) -> None:
    client, db_path = _setup(tmp_path)
    connection = connect(db_path, require_exists=True)
    try:
        service = EvidenceRegistryService(connection)
        expected_ids: set[str] = set()
        for index in range(3):
            source = tmp_path / f"evidence-{index}.txt"
            source.write_text(f"synthetic-{index}", encoding="utf-8")
            registered = service.register(source, evidence_code=f"PAGE-{index}")
            expected_ids.add(str(registered["id"]))
    finally:
        connection.close()
    client = TestClient(create_api_app(db_path, cursor_signing_key=b"local-cursor-test-key-at-least-32-bytes"))
    headers = {"Authorization": f"Bearer {_token(client, 'review')}"}

    offset_page = client.get("/api/v1/evidence?limit=1&offset=1", headers=headers)
    first = client.get("/api/v1/evidence?pagination=cursor&limit=2", headers=headers)
    token = first.json()["pagination"]["next_cursor"]
    second = client.get(f"/api/v1/evidence?pagination=cursor&limit=2&cursor={token}", headers=headers)
    tampered = client.get(f"/api/v1/evidence?pagination=cursor&limit=2&status=available&cursor={token}", headers=headers)

    assert offset_page.status_code == 200
    assert offset_page.json()["pagination"] == {"limit": 1, "offset": 1, "returned": 1}
    assert first.status_code == 200 and token
    assert second.status_code == 200
    assert len(first.json()["evidence"]) == 2
    assert len(second.json()["evidence"]) == 1
    assert {record["id"] for record in first.json()["evidence"] + second.json()["evidence"]} == expected_ids
    assert tampered.status_code == 400
    assert tampered.json()["error"]["code"] == "cursor_context_mismatch"
