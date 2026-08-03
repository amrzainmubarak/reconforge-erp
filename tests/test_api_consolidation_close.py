from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.auth.service import LocalAuthService
from reconforge.db import connect, run_migrations
from reconforge.domain.consolidation_lifecycle import prepare_consolidation_worksheet
from reconforge.infrastructure.sqlite_consolidation_close import SQLiteConsolidationCloseRepository
from tests.test_sqlite_consolidation_close import _worksheet


def test_consolidation_close_api_is_scoped_replay_checked_and_read_only(tmp_path: Path) -> None:
    db_path = tmp_path / "consolidation-api.db"
    run_migrations(db_path)
    connection = connect(db_path)
    admin = LocalAuthService(connection).init_admin(username="admin", password="Secret-123")
    repository = SQLiteConsolidationCloseRepository(connection)
    period = repository.create_period(
        group_code="GLOBAL-GROUP",
        period_id="2026-08",
        reporting_currency="USD",
        period_start_date="2026-08-01",
        period_end_date="2026-08-31",
        reporting_date="2026-08-01",
        actor_label=admin.username,
    )
    base_worksheet = _worksheet()
    worksheet = prepare_consolidation_worksheet(replace(base_worksheet.request, prepared_by=admin.username))
    run = repository.prepare_run(
        run_number="RUN-001",
        worksheet=worksheet,
        actor_label=admin.username,
    )
    repository.create_period(
        group_code="OTHER-GROUP",
        period_id="2026-08",
        reporting_currency="USD",
        period_start_date="2026-08-01",
        period_end_date="2026-08-31",
        reporting_date="2026-08-01",
        workspace="other",
        actor_label=admin.username,
    )
    connection.close()

    client = TestClient(create_api_app(db_path))
    assert client.get("/api/v1/consolidation-close/summary").status_code == 401
    login = client.post("/api/v1/auth/login", json={"username": "admin", "password": "Secret-123"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    summary = client.get("/api/v1/consolidation-close/summary", headers=headers)
    assert summary.status_code == 200, summary.text
    assert summary.json()["summary"]["periods"] == 1
    periods = client.get("/api/v1/consolidation-close/periods?workspace=default", headers=headers)
    assert periods.status_code == 200
    assert [item["id"] for item in periods.json()["periods"]] == [period["id"]]
    other = client.get("/api/v1/consolidation-close/periods?workspace=other", headers=headers)
    assert other.status_code == 200
    assert len(other.json()["periods"]) == 1
    assert other.json()["periods"][0]["id"] != period["id"]

    runs = client.get("/api/v1/consolidation-close/runs?workspace=default", headers=headers)
    assert runs.status_code == 200
    assert [item["id"] for item in runs.json()["runs"]] == [run["id"]]
    detail = client.get(f"/api/v1/consolidation-close/runs/{run['id']}", headers=headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["run"]["worksheet"]["worksheet_id"] == run["worksheet_id"]
    assert detail.json()["run"]["journal_lines"]
    assert detail.json()["run"]["effects"] == []
    assert detail.json()["source"]["kind"] == "sqlite-consolidation-close"

    tamper = connect(db_path)
    try:
        tamper.execute("DROP TRIGGER consolidation_runs_guard_update")
        tamper.execute(
            "UPDATE consolidation_runs SET worksheet_payload=worksheet_payload || ' ' WHERE id=?",
            (run["id"],),
        )
        tamper.commit()
    finally:
        tamper.close()
    rejected = client.get(f"/api/v1/consolidation-close/runs/{run['id']}", headers=headers)
    assert rejected.status_code == 400
    assert rejected.json()["error"]["code"] == "consolidation_run_failed"


def test_consolidation_close_api_rejects_unknown_workspace(tmp_path: Path) -> None:
    db_path = tmp_path / "consolidation-api-empty.db"
    run_migrations(db_path)
    connection = connect(db_path)
    LocalAuthService(connection).init_admin(username="admin", password="Secret-123")
    connection.close()
    client = TestClient(create_api_app(db_path))
    login = client.post("/api/v1/auth/login", json={"username": "admin", "password": "Secret-123"})
    response = client.get(
        "/api/v1/consolidation-close/periods?workspace=does-not-exist",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "consolidation_periods_failed"
