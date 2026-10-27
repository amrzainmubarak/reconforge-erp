"""Independent HTTP regressions for leave ownership and durable state transitions.

Use the real authentication, routing, migrations and SQLite adapter. Failure
injection is a database trigger, so atomicity is checked at the persisted
business boundary rather than by reproducing transaction implementation.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from threading import Barrier, Event

import pytest
from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.auth import LocalAuthService
from reconforge.db import connect, run_migrations
from reconforge.domain.hcm_leave import LeaveEntitlementBalance, LeaveRequest
from reconforge.infrastructure.sqlite_hcm_leave import SqliteHCMLeaveRepository

BASE = "/api/v1/hcm/leave"
PASSWORD = "Synthetic-leave-test-123!"


@pytest.fixture()
def leave_api(tmp_path: Path) -> Iterator[tuple[TestClient, Path, dict[str, dict[str, str]]]]:
    db_path = tmp_path / "leave-authorization.db"
    run_migrations(db_path)
    with connect(db_path, require_exists=True) as connection:
        auth = LocalAuthService(connection)
        auth.init_admin(username="manager", password=PASSWORD)
        for username in ("alice", "bob"):
            auth.create_user(username=username, password=PASSWORD, role="reviewer")
        for role, permissions in (
            ("reviewer", ("people_project_payroll.personnel",)),
            ("admin", ("people_project_payroll.approve_time", "people_project_payroll.manage")),
        ):
            role_id = connection.execute("SELECT id FROM roles WHERE name = ?", (role,)).fetchone()[0]
            for permission in permissions:
                connection.execute(
                    "INSERT OR IGNORE INTO permissions(name, description) VALUES (?, ?)",
                    (permission, "Explicit synthetic leave regression grant"),
                )
                connection.execute(
                    "INSERT OR IGNORE INTO role_permissions(role_id, permission_name) VALUES (?, ?)",
                    (role_id, permission),
                )
        connection.commit()
        repo = SqliteHCMLeaveRepository(connection)
        owner = auth.users.get_by_username("alice")
        assert owner is not None
        repo.bind_employee("default", "EMP-ALICE", owner.id)
        repo.save_balance("default", LeaveEntitlementBalance("EMP-ALICE", "Annual", 30, 20, 0))
        repo.save_request(
            "default",
            LeaveRequest(
                request_id="REQ-ALICE",
                employee_id="EMP-ALICE",
                employee_user_id="alice",
                leave_type="Annual",
                start_date="2026-12-01",
                end_date="2026-12-05",
                requested_days=5,
                status="Submitted",
                reason="Synthetic family leave",
            ),
        )
    with TestClient(create_api_app(db_path), raise_server_exceptions=False) as client:
        headers = {}
        for username in ("alice", "bob", "manager"):
            response = client.post("/api/v1/auth/login", json={"username": username, "password": PASSWORD})
            assert response.status_code == 200, response.text
            headers[username] = {"Authorization": f"Bearer {response.json()['access_token']}"}
        yield client, db_path, headers


def _business_state(db_path: Path) -> tuple[tuple[object, ...], tuple[object, ...], tuple[object, ...]]:
    with sqlite3.connect(db_path) as connection:
        request = connection.execute(
            "SELECT * FROM hcm_leave_requests WHERE workspace_id='default' AND request_id='REQ-ALICE'"
        ).fetchone()
        balance = connection.execute(
            "SELECT * FROM hcm_leave_entitlement_balances WHERE workspace_id='default' AND employee_id='EMP-ALICE'"
        ).fetchone()
        audit = connection.execute("SELECT * FROM audit_events WHERE object_type='hcm.leave' ORDER BY sequence").fetchall()
    assert request is not None and balance is not None
    return tuple(request), tuple(balance), tuple(audit)


@pytest.mark.parametrize("forged_body", [None, {"employee_user_id": "alice", "actor_user_id": "alice"}])
def test_unrelated_reader_cannot_withdraw_another_employees_request(
    leave_api: tuple[TestClient, Path, dict[str, dict[str, str]]], forged_body: dict[str, str] | None
) -> None:
    client, db_path, headers = leave_api
    before = _business_state(db_path)
    response = client.post(f"{BASE}/requests/REQ-ALICE/withdraw", headers=headers["bob"], json=forged_body)
    assert response.status_code == 403, response.text
    assert _business_state(db_path) == before


def test_owner_can_withdraw_own_submitted_request(
    leave_api: tuple[TestClient, Path, dict[str, dict[str, str]]]
) -> None:
    client, db_path, headers = leave_api
    before_balance = _business_state(db_path)[1]
    response = client.post(f"{BASE}/requests/REQ-ALICE/withdraw", headers=headers["alice"])
    assert response.status_code == 200, response.text
    assert response.json()["leave_status"] == "Cancelled"
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT status FROM hcm_leave_requests").fetchone() == ("Cancelled",)
    assert _business_state(db_path)[1] == before_balance
    with sqlite3.connect(db_path) as connection:
        event = connection.execute(
            "SELECT action,metadata_json FROM audit_events WHERE object_type='hcm.leave' AND object_id='REQ-ALICE'"
        ).fetchone()
        assert event is not None and event[0] == "leave_withdrawn"
        assert "Synthetic family leave" not in event[1]


def test_unknown_withdrawal_does_not_mutate_existing_request(
    leave_api: tuple[TestClient, Path, dict[str, dict[str, str]]]
) -> None:
    client, db_path, headers = leave_api
    before = _business_state(db_path)
    response = client.post(f"{BASE}/requests/REQ-MISSING/withdraw", headers=headers["alice"])
    assert response.status_code == 404, response.text
    assert _business_state(db_path) == before


@pytest.mark.parametrize("operation", ["read", "unpaid-deduction"])
def test_personnel_permission_does_not_reveal_another_employees_request(
    leave_api: tuple[TestClient, Path, dict[str, dict[str, str]]], operation: str,
) -> None:
    client, db_path, headers = leave_api
    before = _business_state(db_path)
    path = f"{BASE}/requests/REQ-ALICE"
    response = (
        client.get(path, headers=headers["bob"])
        if operation == "read"
        else client.post(path + "/unpaid-deduction", headers=headers["bob"], json={"daily_rate_minor": 1000})
    )
    assert response.status_code == 403, response.text
    assert "Synthetic family leave" not in response.text
    assert _business_state(db_path) == before


def test_existing_session_loses_leave_authority_after_permission_revocation(
    leave_api: tuple[TestClient, Path, dict[str, dict[str, str]]],
) -> None:
    client, db_path, headers = leave_api
    before = _business_state(db_path)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "DELETE FROM role_permissions WHERE role_id=(SELECT id FROM roles WHERE name='reviewer') "
            "AND permission_name='people_project_payroll.personnel'"
        )
    response = client.post(f"{BASE}/requests/REQ-ALICE/withdraw", headers=headers["alice"])
    assert response.status_code == 403, response.text
    assert _business_state(db_path) == before


def test_local_committed_revocation_is_rechecked_after_waiting_for_mutation_admission(
    leave_api: tuple[TestClient, Path, dict[str, dict[str, str]]], monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, db_path, headers = leave_api
    before = _business_state(db_path)
    waiting, release = Event(), Event()
    original = SqliteHCMLeaveRepository.mutation

    @contextmanager
    def gated_mutation(repository: SqliteHCMLeaveRepository) -> Iterator[None]:
        # Synchronize scheduling only. Real authentication, authorization reads,
        # writer acquisition and persisted business mutations remain active.
        waiting.set()
        assert release.wait(timeout=15)
        with original(repository):
            yield

    monkeypatch.setattr(SqliteHCMLeaveRepository, "mutation", gated_mutation)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(client.post, f"{BASE}/requests/REQ-ALICE/withdraw", headers=headers["alice"])
        try:
            assert waiting.wait(timeout=15)
            with sqlite3.connect(db_path) as connection:
                connection.execute(
                    "DELETE FROM role_permissions WHERE role_id=(SELECT id FROM roles WHERE name='reviewer') "
                    "AND permission_name='people_project_payroll.personnel'"
                )
        finally:
            release.set()
        response = pending.result(timeout=15)
    assert response.status_code == 403, response.text
    assert _business_state(db_path) == before


def test_local_personal_employee_scope_is_bound_by_manager_not_request_body(
    leave_api: tuple[TestClient, Path, dict[str, dict[str, str]]],
) -> None:
    client, db_path, headers = leave_api
    before = _business_state(db_path)
    response = client.get(f"{BASE}/balances/EMP-ALICE/Annual", headers=headers["bob"])
    assert response.status_code == 403, response.text
    response = client.post(f"{BASE}/requests", headers=headers["bob"], json={
        "request_id": "BOB-FOREIGN", "employee_id": "EMP-ALICE", "leave_type": "Annual",
        "start_date": "2026-12-01", "end_date": "2026-12-05", "requested_days": 5, "reason": "Synthetic foreign claim",
    })
    assert response.status_code == 403, response.text
    assert _business_state(db_path) == before
    with sqlite3.connect(db_path) as connection:
        bob_id = connection.execute("SELECT id FROM users WHERE username='bob'").fetchone()[0]
    payload = {
        "employee_id": "EMP-BOB", "employee_user_id": bob_id, "leave_type": "Annual",
        "annual_entitlement_days": 30, "accrued_days": 20,
    }
    assert client.post(f"{BASE}/balances", headers=headers["bob"], json=payload).status_code == 403
    response = client.post(f"{BASE}/balances", headers=headers["manager"], json=payload)
    assert response.status_code == 200, response.text
    assert client.get(f"{BASE}/balances/EMP-BOB/Annual", headers=headers["bob"]).status_code == 200
    response = client.post(f"{BASE}/requests", headers=headers["bob"], json={
        "request_id": "BOB-OWN", "employee_id": "EMP-BOB", "leave_type": "Annual",
        "start_date": "2026-12-01", "end_date": "2026-12-05", "requested_days": 5, "reason": "Synthetic own claim",
    })
    assert response.status_code == 200, response.text
    # The successful Bob operations correctly append their own business audit.
    # Compare the denied reassignment against the immediately preceding state.
    before_rebind = _business_state(db_path)
    response = client.post(f"{BASE}/balances", headers=headers["manager"], json={**payload, "employee_id": "EMP-ALICE"})
    assert response.status_code == 409, response.text
    assert _business_state(db_path) == before_rebind
    assert _business_state(db_path)[:2] == before[:2]


@pytest.mark.parametrize("identity_mode", ["stable", "legacy", "unbound"])
def test_local_leave_identity_survives_rename_without_legacy_alias_selfclaim(
    leave_api: tuple[TestClient, Path, dict[str, dict[str, str]]], identity_mode: str,
) -> None:
    client, db_path, headers = leave_api
    identifier = "REQ-ALICE"
    if identity_mode == "stable":
        identifier = "REQ-STABLE"
        response = client.post(f"{BASE}/requests", headers=headers["alice"], json={
            "request_id": identifier, "employee_id": "EMP-ALICE", "leave_type": "Annual",
            "start_date": "2026-12-01", "end_date": "2026-12-05", "requested_days": 5, "reason": "Synthetic stable identity",
        })
        assert response.status_code == 200, response.text
    with sqlite3.connect(db_path) as connection:
        owner_id = connection.execute("SELECT id FROM users WHERE username='alice'").fetchone()[0]
        assert owner_id != "alice"
        connection.execute("UPDATE users SET username='alice-renamed' WHERE id=?", (owner_id,))
        connection.execute("UPDATE users SET username='alice' WHERE username='bob'")
        if identity_mode == "unbound":
            connection.execute("DELETE FROM hcm_employee_identities WHERE employee_id='EMP-ALICE'")
    before = _business_state(db_path)
    response = client.get(f"{BASE}/requests/{identifier}", headers=headers["alice"])
    assert response.status_code == (403 if identity_mode == "unbound" else 200), response.text
    if identity_mode != "unbound":
        assert response.json()["employee_user_id"] == (owner_id if identity_mode == "stable" else "alice")
    denied = client.get(f"{BASE}/requests/{identifier}", headers=headers["bob"])
    assert denied.status_code == 403, denied.text
    assert _business_state(db_path) == before
    with sqlite3.connect(db_path) as connection:
        connection.execute("INSERT INTO roles(id,name) VALUES('rename-owner-reviewer','rename-owner-reviewer')")
        connection.execute("INSERT INTO role_permissions VALUES('rename-owner-reviewer','people_project_payroll.approve_time')")
        connection.execute("INSERT INTO user_roles VALUES(?,'rename-owner-reviewer')", (owner_id,))
    for action in ("approve", "reject"):
        response = client.post(
            f"{BASE}/requests/{identifier}/{action}", headers=headers["alice"],
            json={"rejection_reason": "Synthetic self review"} if action == "reject" else None,
        )
        assert response.status_code == (403 if identity_mode == "unbound" else 400), response.text
        assert _business_state(db_path) == before
    if identity_mode != "unbound":
        response = client.post(f"{BASE}/requests/{identifier}/withdraw", headers=headers["alice"])
        assert response.status_code == 200, response.text
        with sqlite3.connect(db_path) as connection:
            row = connection.execute("SELECT employee_user_id,status FROM hcm_leave_requests WHERE request_id=?", (identifier,)).fetchone()
        assert row == (owner_id if identity_mode == "stable" else "alice", "Cancelled")


def test_local_leave_review_records_stable_actor_and_keeps_display_label(
    leave_api: tuple[TestClient, Path, dict[str, dict[str, str]]],
) -> None:
    client, db_path, headers = leave_api
    with sqlite3.connect(db_path) as connection:
        manager_id = connection.execute("SELECT id FROM users WHERE username='manager'").fetchone()[0]
    assert manager_id != "manager"
    response = client.post(f"{BASE}/requests/REQ-ALICE/approve", headers=headers["manager"])
    assert response.status_code == 200, response.text
    assert response.json()["approved_by"] == "manager"
    assert response.json()["approved_by_user_id"] == manager_id
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT approved_by_user_id FROM hcm_leave_requests WHERE request_id='REQ-ALICE'").fetchone() == (manager_id,)


def test_unbound_legacy_employee_is_not_self_claimable(
    leave_api: tuple[TestClient, Path, dict[str, dict[str, str]]],
) -> None:
    client, db_path, headers = leave_api
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "INSERT INTO hcm_leave_entitlement_balances VALUES('default','EMP-UNBOUND','Annual',30,20,0)"
        )
    response = client.get(f"{BASE}/balances/EMP-UNBOUND/Annual", headers=headers["alice"])
    assert response.status_code == 403, response.text
    response = client.post(f"{BASE}/requests", headers=headers["alice"], json={
        "request_id": "LEGACY-CLAIM", "employee_id": "EMP-UNBOUND", "leave_type": "Annual",
        "start_date": "2026-12-01", "end_date": "2026-12-05", "requested_days": 5, "reason": "Synthetic claim",
    })
    assert response.status_code == 403, response.text
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT count(*) FROM hcm_employee_identities WHERE employee_id='EMP-UNBOUND'").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM hcm_leave_requests WHERE request_id='LEGACY-CLAIM'").fetchone() == (0,)


def test_owner_with_approval_permission_cannot_approve_own_request(
    leave_api: tuple[TestClient, Path, dict[str, dict[str, str]]]
) -> None:
    client, db_path, headers = leave_api
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "INSERT INTO role_permissions(role_id, permission_name) "
            "SELECT id, 'people_project_payroll.approve_time' FROM roles WHERE name='reviewer'"
        )
    before = _business_state(db_path)
    response = client.post(f"{BASE}/requests/REQ-ALICE/approve", headers=headers["alice"])
    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "leave_self_approval_prohibited"
    assert _business_state(db_path) == before


@pytest.mark.parametrize("action", ["approve", "reject"])
def test_canonical_local_employee_cannot_review_a_forged_legacy_owner(
    leave_api: tuple[TestClient, Path, dict[str, dict[str, str]]], action: str,
) -> None:
    client, db_path, headers = leave_api
    with sqlite3.connect(db_path) as connection:
        connection.execute("UPDATE hcm_leave_requests SET employee_user_id='bob' WHERE request_id='REQ-ALICE'")
        connection.execute(
            "INSERT INTO role_permissions(role_id, permission_name) "
            "SELECT id, 'people_project_payroll.approve_time' FROM roles WHERE name='reviewer'"
        )
    before = _business_state(db_path)
    body = {"rejection_reason": "Synthetic rejection"} if action == "reject" else None
    response = client.post(f"{BASE}/requests/REQ-ALICE/{action}", headers=headers["alice"], json=body)
    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == f"leave_self_{'approval' if action == 'approve' else 'rejection'}_prohibited"
    assert _business_state(db_path) == before


@pytest.mark.parametrize("operation", ["approve", "cancel"])
def test_balance_write_failure_cannot_partially_persist_leave_transition(
    leave_api: tuple[TestClient, Path, dict[str, dict[str, str]]], operation: str
) -> None:
    client, db_path, headers = leave_api
    with sqlite3.connect(db_path) as connection:
        if operation == "cancel":
            connection.execute("UPDATE hcm_leave_requests SET status='Approved', approved_by_user_id='manager'")
            connection.execute("UPDATE hcm_leave_entitlement_balances SET consumed_days=5")
        connection.executescript(
            "CREATE TRIGGER reject_synthetic_balance_update BEFORE UPDATE ON hcm_leave_entitlement_balances "
            "BEGIN SELECT RAISE(ABORT, 'synthetic leave balance write failure'); END;"
        )
    before = _business_state(db_path)
    payload = {"current_date": "2026-11-01"} if operation == "cancel" else None
    response = client.post(f"{BASE}/requests/REQ-ALICE/{operation}", headers=headers["manager"], json=payload)
    assert response.status_code >= 400, response.text
    assert _business_state(db_path) == before, "Rejected operation durably changed leave request or balance"


def test_audit_write_failure_rolls_back_leave_request_and_balance(
    leave_api: tuple[TestClient, Path, dict[str, dict[str, str]]],
) -> None:
    client, db_path, headers = leave_api
    with sqlite3.connect(db_path) as connection:
        connection.executescript(
            "CREATE TRIGGER reject_leave_business_audit BEFORE INSERT ON audit_events "
            "WHEN NEW.object_type='hcm.leave' BEGIN SELECT RAISE(ABORT,'synthetic audit write failure'); END;"
        )
    before = _business_state(db_path)
    response = client.post(f"{BASE}/requests/REQ-ALICE/approve", headers=headers["manager"])
    assert response.status_code >= 400, response.text
    assert _business_state(db_path) == before


@pytest.mark.parametrize("initial_status", ["Submitted", "Approved", "Cancelled"])
def test_duplicate_submission_cannot_rewrite_another_owners_request(
    leave_api: tuple[TestClient, Path, dict[str, dict[str, str]]], initial_status: str
) -> None:
    client, db_path, headers = leave_api
    with sqlite3.connect(db_path) as connection:
        connection.execute("UPDATE hcm_leave_requests SET status=?", (initial_status,))
        if initial_status == "Approved":
            connection.execute("UPDATE hcm_leave_entitlement_balances SET consumed_days=5")
    before = _business_state(db_path)
    response = client.post(
        f"{BASE}/requests",
        headers=headers["bob"],
        json={
            "request_id": "REQ-ALICE", "employee_id": "EMP-ALICE", "leave_type": "Annual",
            "start_date": "2026-12-01", "end_date": "2026-12-05", "requested_days": 3,
            "reason": "Another reader attempted to replace the original request",
        },
    )
    assert response.status_code in (403, 409), response.text
    assert _business_state(db_path) == before


def _concurrent_posts(client: TestClient, paths: list[str], headers: dict[str, str], payload: object = None) -> list[int]:
    start = Barrier(len(paths))

    def post(path: str) -> int:
        start.wait(timeout=10)
        return client.post(path, headers=headers, json=payload).status_code

    with ThreadPoolExecutor(max_workers=len(paths)) as pool:
        return list(pool.map(post, paths))


def test_concurrent_approval_of_one_request_consumes_balance_once(
    leave_api: tuple[TestClient, Path, dict[str, dict[str, str]]]
) -> None:
    client, db_path, headers = leave_api
    path = f"{BASE}/requests/REQ-ALICE/approve"
    statuses = _concurrent_posts(client, [path, path], headers["manager"])
    assert sorted(statuses) == [200, 400]
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT status FROM hcm_leave_requests").fetchone() == ("Approved",)
        assert connection.execute("SELECT consumed_days FROM hcm_leave_entitlement_balances").fetchone() == (5,)


def test_concurrent_requests_cannot_overdraw_shared_entitlement(
    leave_api: tuple[TestClient, Path, dict[str, dict[str, str]]]
) -> None:
    client, db_path, headers = leave_api
    with sqlite3.connect(db_path) as connection:
        connection.execute("UPDATE hcm_leave_requests SET requested_days=15")
        connection.execute(
            "INSERT INTO hcm_leave_requests SELECT workspace_id, 'REQ-ALICE-2', employee_id, employee_user_id, "
            "leave_type, start_date, end_date, requested_days, status, reason, approved_by_user_id, rejection_reason "
            "FROM hcm_leave_requests WHERE request_id='REQ-ALICE'"
        )
    paths = [f"{BASE}/requests/{request_id}/approve" for request_id in ("REQ-ALICE", "REQ-ALICE-2")]
    statuses = _concurrent_posts(client, paths, headers["manager"])
    assert sorted(statuses) == [200, 400]
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT consumed_days FROM hcm_leave_entitlement_balances").fetchone() == (15,)
        assert connection.execute("SELECT COUNT(*) FROM hcm_leave_requests WHERE status='Approved'").fetchone() == (1,)
        assert connection.execute("SELECT COUNT(*) FROM hcm_leave_requests WHERE status='Submitted'").fetchone() == (1,)


def test_concurrent_cancellation_of_one_request_restores_balance_once(
    leave_api: tuple[TestClient, Path, dict[str, dict[str, str]]]
) -> None:
    client, db_path, headers = leave_api
    with sqlite3.connect(db_path) as connection:
        connection.execute("UPDATE hcm_leave_requests SET status='Approved', approved_by_user_id='manager'")
        connection.execute("UPDATE hcm_leave_entitlement_balances SET consumed_days=5")
    path = f"{BASE}/requests/REQ-ALICE/cancel"
    statuses = _concurrent_posts(client, [path, path], headers["manager"], {"current_date": "2026-11-01"})
    assert sorted(statuses) == [200, 400]
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT status FROM hcm_leave_requests").fetchone() == ("Cancelled",)
        assert connection.execute("SELECT consumed_days FROM hcm_leave_entitlement_balances").fetchone() == (0,)


def test_stale_session_refresh_releases_owned_sqlite_write_transaction(
    leave_api: tuple[TestClient, Path, dict[str, dict[str, str]]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A competing session refresh can make the conditional UPDATE affect zero rows.

    Advance another real connection exactly after authentication reads the old
    session. Its zero-row UPDATE must not retain a lock that blocks a separate
    business connection in the same HTTP request.
    """
    from reconforge.api.security import authenticate_token, token_hash
    from reconforge.auth.repositories import UserRepository
    from reconforge.domain.models import utc_now_text

    _client, db_path, headers = leave_api
    token = headers["manager"]["Authorization"].split(" ", 1)[1]
    original = UserRepository.get_by_username

    def concurrent_refresh(repository: UserRepository, username: str) -> object:
        result = original(repository, username)
        with sqlite3.connect(db_path) as competitor:
            competitor.execute(
                "UPDATE api_sessions SET last_used_at=? WHERE token_hash=?", (utc_now_text(), token_hash(token))
            )
        return result

    monkeypatch.setattr(UserRepository, "get_by_username", concurrent_refresh)
    with connect(db_path, require_exists=True) as connection:
        assert not connection.in_transaction
        user = authenticate_token(connection, token=token)
        assert user is not None and user.username == "manager"
        assert not connection.in_transaction, "Zero-row session UPDATE retained its own SQLite write transaction"


def test_session_refresh_does_not_commit_its_callers_existing_transaction(
    leave_api: tuple[TestClient, Path, dict[str, dict[str, str]]]
) -> None:
    from reconforge.api.security import authenticate_token

    _client, db_path, headers = leave_api
    token = headers["manager"]["Authorization"].split(" ", 1)[1]
    connection = connect(db_path, require_exists=True)
    try:
        connection.execute("UPDATE users SET display_name='Pending caller change' WHERE username='manager'")
        assert connection.in_transaction
        user = authenticate_token(connection, token=token)
        assert user is not None and user.username == "manager"
        assert connection.in_transaction, "Session refresh committed the caller's unrelated pending mutation"
        connection.rollback()
        assert connection.execute("SELECT display_name FROM users WHERE username='manager'").fetchone()[0] == "manager"
    finally:
        connection.close()
