from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.api.routes import consolidation_close as consolidation_routes
from reconforge.api.server_identity import RequestExecutionScope
from reconforge.auth.service import LocalAuthService
from reconforge.db import connect, run_migrations
from reconforge.domain.consolidation_lifecycle import prepare_consolidation_worksheet
from reconforge.infrastructure.sqlite_consolidation_close import SQLiteConsolidationCloseRepository
from tests.test_sqlite_consolidation_close import _post, _worksheet


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
    assert detail.json()["run"]["translation_evidence"]["result_digest"] == run["translation_result_digest"]
    assert detail.json()["run"]["translation_evidence"]["line_count"] == 4
    assert detail.json()["run"]["management_statement"]["total_balance"]["amount"] == "0.00"
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


def test_consolidation_close_api_creates_strict_period_and_replays(tmp_path: Path) -> None:
    db_path = tmp_path / "consolidation-api-create.db"
    run_migrations(db_path)
    connection = connect(db_path)
    LocalAuthService(connection).init_admin(username="admin", password="Secret-123")
    connection.close()
    client = TestClient(create_api_app(db_path))
    login = client.post("/api/v1/auth/login", json={"username": "admin", "password": "Secret-123"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    payload = {
        "group_code": "GLOBAL-GROUP",
        "period_id": "2026-09",
        "reporting_currency": "USD",
        "period_start_date": "2026-09-01",
        "period_end_date": "2026-09-30",
        "reporting_date": "2026-09-30",
        "workspace": "default",
    }
    created = client.post("/api/v1/consolidation-close/periods", headers=headers, json=payload)
    assert created.status_code == 200, created.text
    assert created.json()["period"]["period_name"] == "2026-09"
    assert created.json()["source"]["kind"] == "sqlite-consolidation-close"
    replay = client.post("/api/v1/consolidation-close/periods", headers=headers, json=payload)
    assert replay.status_code == 200, replay.text
    assert replay.json()["period"]["id"] == created.json()["period"]["id"]
    invalid = {**payload, "unexpected": True}
    rejected = client.post("/api/v1/consolidation-close/periods", headers=headers, json=invalid)
    assert rejected.status_code == 422


def test_consolidation_close_api_runs_full_governed_lifecycle(tmp_path: Path) -> None:
    db_path = tmp_path / "consolidation-api-lifecycle.db"
    run_migrations(db_path)
    connection = connect(db_path)
    auth = LocalAuthService(connection)
    auth.init_admin(username="admin", password="Secret-123")
    auth.create_user(username="reviewer", password="Secret-123", role="reviewer")
    auth.create_user(username="poster", password="Secret-123", role="reviewer")
    connection.close()
    client = TestClient(create_api_app(db_path))

    def headers(username: str) -> dict[str, str]:
        login = client.post("/api/v1/auth/login", json={"username": username, "password": "Secret-123"})
        assert login.status_code == 200, login.text
        return {"Authorization": f"Bearer {login.json()['access_token']}"}

    admin_headers = headers("admin")
    reviewer_headers = headers("reviewer")
    poster_headers = headers("poster")
    period = client.post(
        "/api/v1/consolidation-close/periods",
        headers=admin_headers,
        json={
            "group_code": "GLOBAL-GROUP",
            "period_id": "2026-08",
            "reporting_currency": "USD",
            "period_start_date": "2026-08-01",
            "period_end_date": "2026-08-31",
            "reporting_date": "2026-08-01",
        },
    )
    assert period.status_code == 200, period.text
    worksheet = prepare_consolidation_worksheet(replace(_worksheet().request, prepared_by="admin"))
    prepared = client.post(
        "/api/v1/consolidation-close/runs",
        headers=admin_headers,
        json={"run_number": "RUN-API-001", "worksheet": worksheet.to_dict()},
    )
    assert prepared.status_code == 200, prepared.text
    run = prepared.json()["run"]
    assert run["status"] == "Prepared"
    run_id = run["id"]

    approved = client.post(
        f"/api/v1/consolidation-close/runs/{run_id}/approve",
        headers=reviewer_headers,
        json={"expected_version": 1, "reason": "Independent worksheet review."},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["run"]["status"] == "Approved"
    posted = client.post(
        f"/api/v1/consolidation-close/runs/{run_id}/post",
        headers=poster_headers,
        json={"expected_version": 2, "reason": "Control journal posting approved."},
    )
    assert posted.status_code == 200, posted.text
    assert posted.json()["run"]["status"] == "Posted"
    reversal = client.post(
        f"/api/v1/consolidation-close/runs/{run_id}/reversal/request",
        headers=admin_headers,
        json={"expected_version": 3, "reason": "Synthetic reversal request."},
    )
    assert reversal.status_code == 200, reversal.text
    assert reversal.json()["run"]["status"] == "ReversalPrepared"
    reversed_run = client.post(
        f"/api/v1/consolidation-close/runs/{run_id}/reversal/approve",
        headers=reviewer_headers,
        json={"expected_version": 4, "reason": "Independent reversal approval."},
    )
    assert reversed_run.status_code == 200, reversed_run.text
    assert reversed_run.json()["run"]["status"] == "Reversed"

    period_id = period.json()["period"]["id"]
    locked = client.post(
        f"/api/v1/consolidation-close/periods/{period_id}/lock",
        headers=reviewer_headers,
        json={"expected_version": 1, "reason": "Close period locked."},
    )
    assert locked.status_code == 200, locked.text
    assert locked.json()["period"]["status"] == "Locked"
    reopened = client.post(
        f"/api/v1/consolidation-close/periods/{period_id}/reopen",
        headers=admin_headers,
        json={"expected_version": 2, "reason": "Independent reopen review."},
    )
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["period"]["status"] == "Reopened"


def test_consolidation_close_certification_api_is_posted_only_and_maker_checker_bound(tmp_path: Path) -> None:
    db_path = tmp_path / "consolidation-certification-api.db"
    run_migrations(db_path)
    connection = connect(db_path)
    auth = LocalAuthService(connection)
    admin = auth.init_admin(username="admin", password="Secret-123")
    auth.create_user(username="reviewer", password="Secret-123", role="reviewer")
    repository = SQLiteConsolidationCloseRepository(connection)
    repository.create_period(
        group_code="GLOBAL-GROUP",
        period_id="2026-08",
        reporting_currency="USD",
        period_start_date="2026-08-01",
        period_end_date="2026-08-31",
        reporting_date="2026-08-01",
        actor_label=admin.username,
    )
    worksheet = prepare_consolidation_worksheet(
        replace(_worksheet().request, prepared_by=admin.username)
    )
    run = repository.prepare_run(run_number="RUN-CERT", worksheet=worksheet, actor_label=admin.username)
    posted = _post(repository, run)
    connection.close()

    client = TestClient(create_api_app(db_path))
    admin_login = client.post("/api/v1/auth/login", json={"username": "admin", "password": "Secret-123"})
    admin_headers = {"Authorization": f"Bearer {admin_login.json()['access_token']}"}
    prepared = client.post(
        f"/api/v1/consolidation-close/runs/{posted['id']}/certification",
        json={"note": "Posted close evidence prepared."},
        headers=admin_headers,
    )
    assert prepared.status_code == 200, prepared.text
    assert prepared.json()["certification"]["status"] == "Prepared"
    reviewer_login = client.post(
        "/api/v1/auth/login", json={"username": "reviewer", "password": "Secret-123"}
    )
    reviewer_headers = {"Authorization": f"Bearer {reviewer_login.json()['access_token']}"}
    reviewed = client.post(
        f"/api/v1/consolidation-close/runs/{posted['id']}/certification/review",
        json={"note": "Independent review completed."},
        headers=reviewer_headers,
    )
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["certification"]["status"] == "Reviewed"
    fetched = client.get(
        f"/api/v1/consolidation-close/runs/{posted['id']}/certification",
        headers=admin_headers,
    )
    assert fetched.status_code == 200
    assert fetched.json()["certification"]["reviewed_by"] == "reviewer"
    assert fetched.json()["certification"]["object_type"] == "consolidation_close_run"


def test_consolidation_close_server_boundary_binds_workspace_before_exposure(
    tmp_path: Path, monkeypatch: object
) -> None:
    """The server adapter must reject a tenant row from a sibling workspace."""

    db_path = tmp_path / "consolidation-server-boundary.db"
    scoped_permissions: list[dict[str, object]] = []
    run_migrations(db_path)
    connection = connect(db_path)
    LocalAuthService(connection).init_admin(username="admin", password="Secret-123")
    connection.close()
    client = TestClient(create_api_app(db_path))
    login = client.post("/api/v1/auth/login", json={"username": "admin", "password": "Secret-123"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    class Repository:
        def create_period(self, **kwargs: object) -> dict[str, object]:
            return {"id": "period-a", "workspace_id": str(kwargs["workspace"]), "period_name": "2026-09"}

        def list_periods(self, **_: object) -> list[dict[str, object]]:
            return [{"id": "period-b", "workspace_id": "workspace-b"}]

        def get_run(self, *_: object, **__: object) -> dict[str, object]:
            return {"id": "run-b", "workspace_id": "workspace-b"}

        def attach_intercompany_artifact(self, *_: object, **__: object) -> dict[str, object]:
            return {"id": "link-a", "artifact_id": "ice-" + "a" * 32, "matched_elimination_ids": ["ELIM-1"]}

    repository = Repository()

    def execute(_request: object, operation: object) -> object:
        return operation(repository, "tenant-a")  # type: ignore[operator]

    monkeypatch.setattr(consolidation_routes, "server_consolidation_close_enabled", lambda _request: True)
    monkeypatch.setattr(
        consolidation_routes,
        "enforce_server_scoped_permission",
        lambda _request, **kwargs: scoped_permissions.append(kwargs),
    )
    monkeypatch.setattr(
        consolidation_routes,
        "request_execution_scope",
        lambda _request: RequestExecutionScope(
            tenant_id="tenant-a", workspace_id="workspace-a", organization_id="org-a", legal_entity_id="entity-a"
        ),
    )
    monkeypatch.setattr(consolidation_routes, "execute_postgres_consolidation_close", execute)

    listed = client.get("/api/v1/consolidation-close/periods", headers=headers)
    assert listed.status_code == 403
    assert listed.json()["error"]["code"] == "workspace_scope_denied"

    created = client.post(
        "/api/v1/consolidation-close/periods",
        headers=headers,
        json={
            "group_code": "GLOBAL-GROUP",
            "period_id": "2026-09",
            "reporting_currency": "USD",
            "period_start_date": "2026-09-01",
            "period_end_date": "2026-09-30",
            "reporting_date": "2026-09-30",
        },
    )
    assert created.status_code == 200
    assert created.json()["period"]["workspace_id"] == "workspace-a"
    assert scoped_permissions == [
        {"permission": "finance_core.manage", "tenant_id": "tenant-a", "workspace_id": "workspace-a"}
    ]

    sibling_create = client.post(
        "/api/v1/consolidation-close/periods",
        headers=headers,
        json={
            "group_code": "GLOBAL-GROUP",
            "period_id": "2026-10",
            "reporting_currency": "USD",
            "period_start_date": "2026-10-01",
            "period_end_date": "2026-10-31",
            "reporting_date": "2026-10-31",
            "workspace": "workspace-b",
        },
    )
    assert sibling_create.status_code == 403
    assert sibling_create.json()["error"]["code"] == "workspace_scope_denied"

    detail = client.get("/api/v1/consolidation-close/runs/run-b", headers=headers)
    assert detail.status_code == 403
    assert detail.json()["error"]["code"] == "workspace_scope_denied"

    attached = client.post(
        "/api/v1/consolidation-close/runs/run-a/intercompany-evidence",
        headers=headers,
        json={"artifact_id": "ice-" + "a" * 32},
    )
    assert attached.status_code == 200
    assert attached.json()["link"]["artifact_id"] == "ice-" + "a" * 32
    assert scoped_permissions[-1] == {
        "permission": "finance_core.manage",
        "tenant_id": "tenant-a",
        "workspace_id": "workspace-a",
    }
