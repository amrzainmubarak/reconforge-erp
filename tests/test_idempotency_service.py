from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from reconforge.application.idempotency import (
    IdempotencyApplicationService,
    IdempotencyConflictError,
    IdempotencyError,
    IdempotencyInProgressError,
    IdempotencyOwnershipError,
)
from reconforge.db import connect, run_migrations
from reconforge.db.backup import create_backup, restore_backup
from reconforge.infrastructure.sqlite_idempotency import SQLiteIdempotencyRepository

CREATED = "2026-07-27T10:00:00Z"
EXPIRES = "2026-07-27T11:00:00Z"


def _service(connection: sqlite3.Connection) -> IdempotencyApplicationService:
    return IdempotencyApplicationService(SQLiteIdempotencyRepository(connection))


def test_sqlite_idempotency_create_complete_replay_conflict_and_scope(tmp_path: Path) -> None:
    db_path = tmp_path / "idempotency.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        service = _service(connection)
        first = service.begin(
            tenant_id="tenant-a", scope="payments:create", key="request-1", request=b'{"amount":"10.00"}',
            owner_token="worker-1", created_at=CREATED, expires_at=EXPIRES, observed_at=CREATED,
        )
        assert first.created is True and first.replayed is False
        with pytest.raises(IdempotencyInProgressError):
            service.begin(
                tenant_id="tenant-a", scope="payments:create", key="request-1", request=b'{"amount":"10.00"}',
                owner_token="worker-2", created_at=CREATED, expires_at=EXPIRES, observed_at=CREATED,
            )
        with pytest.raises(IdempotencyConflictError):
            service.begin(
                tenant_id="tenant-a", scope="payments:create", key="request-1", request=b'{"amount":"11.00"}',
                owner_token="worker-2", created_at=CREATED, expires_at=EXPIRES, observed_at=CREATED,
            )
        completed = service.complete(
            first.reservation, response=b'{"id":"PAY-1"}', content_type="application/json",
            completed_at="2026-07-27T10:01:00Z",
        )
        replay = service.begin(
            tenant_id="tenant-a", scope="payments:create", key="request-1", request=b'{"amount":"10.00"}',
            owner_token="worker-3", created_at=CREATED, expires_at=EXPIRES,
            observed_at="2026-07-27T10:02:00Z",
        )
        assert replay.replayed is True and replay.reservation == completed
        separate = service.begin(
            tenant_id="tenant-b", scope="payments:create", key="request-1", request=b'{"amount":"10.00"}',
            owner_token="worker-b", created_at=CREATED, expires_at=EXPIRES, observed_at=CREATED,
        )
        assert separate.created is True
    finally:
        connection.close()


def test_sqlite_idempotency_expiry_rebind_and_stale_owner(tmp_path: Path) -> None:
    db_path = tmp_path / "expiry.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        service = _service(connection)
        old = service.begin(
            tenant_id="tenant-a", scope="imports", key="key", request=b"old", owner_token="old-owner",
            created_at=CREATED, expires_at=EXPIRES, observed_at=CREATED,
        ).reservation
        current = service.begin(
            tenant_id="tenant-a", scope="imports", key="key", request=b"new", owner_token="new-owner",
            created_at="2026-07-27T11:00:01Z", expires_at="2026-07-27T12:00:00Z",
            observed_at="2026-07-27T11:00:01Z",
        ).reservation
        assert current.request_digest != old.request_digest
        with pytest.raises(IdempotencyOwnershipError):
            service.complete(old, response=b"stale", content_type="text/plain", completed_at="2026-07-27T11:01:00Z")
    finally:
        connection.close()


def test_sqlite_concurrent_reservation_has_one_owner(tmp_path: Path) -> None:
    db_path = tmp_path / "concurrent.db"
    run_migrations(db_path)

    def reserve(index: int) -> str:
        connection = connect(db_path, require_exists=True)
        try:
            try:
                result = _service(connection).begin(
                    tenant_id="tenant-a", scope="jobs", key="same", request=b"same-request",
                    owner_token=f"worker-{index}", created_at=CREATED, expires_at=EXPIRES, observed_at=CREATED,
                )
                return "created" if result.created else "replayed"
            except IdempotencyInProgressError:
                return "in-progress"
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=8) as executor:
        outcomes = list(executor.map(reserve, range(8)))
    assert outcomes.count("created") == 1
    assert outcomes.count("in-progress") == 7


def test_idempotency_response_limit_fails_before_storage(tmp_path: Path) -> None:
    db_path = tmp_path / "bounded.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        service = IdempotencyApplicationService(SQLiteIdempotencyRepository(connection), max_response_bytes=4)
        reservation = service.begin(
            tenant_id="tenant-a", scope="exports", key="key", request=b"request", owner_token="owner",
            created_at=CREATED, expires_at=EXPIRES, observed_at=CREATED,
        ).reservation
        with pytest.raises(Exception, match="byte limit"):
            service.complete(reservation, response=b"12345", content_type="text/plain", completed_at=CREATED)
        row = connection.execute("SELECT status FROM idempotency_records").fetchone()
        assert row["status"] == "pending"
        with pytest.raises(Exception, match="request.*byte limit"):
            IdempotencyApplicationService(
                SQLiteIdempotencyRepository(connection), max_request_bytes=4
            ).begin(
                tenant_id="tenant-a", scope="exports", key="large-request", request=b"12345",
                owner_token="owner", created_at=CREATED, expires_at=EXPIRES, observed_at=CREATED,
            )
        with pytest.raises(IdempotencyOwnershipError):
            service.complete(
                reservation, response=b"ok", content_type="text/plain", completed_at=EXPIRES,
            )
        with pytest.raises(IdempotencyError, match="tenant scope"):
            service.begin(
                tenant_id="Tenant A", scope="exports", key="invalid", request=b"request",
                owner_token="owner", created_at=CREATED, expires_at=EXPIRES, observed_at=CREATED,
            )
    finally:
        connection.close()


def test_completed_idempotency_response_survives_backup_restore(tmp_path: Path) -> None:
    db_path = tmp_path / "source.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        service = _service(connection)
        reservation = service.begin(
            tenant_id="tenant-a", scope="reports", key="backup", request=b"request", owner_token="owner",
            created_at=CREATED, expires_at=EXPIRES, observed_at=CREATED,
        ).reservation
        service.complete(
            reservation, response=b"binary\x00response", content_type="application/octet-stream",
            completed_at="2026-07-27T10:01:00Z",
        )
    finally:
        connection.close()
    backup = create_backup(db_path, tmp_path / "backup")
    restored = tmp_path / "restored.db"
    restore_backup(restored, backup.backup_path)
    connection = connect(restored, require_exists=True)
    try:
        replay = _service(connection).begin(
            tenant_id="tenant-a", scope="reports", key="backup", request=b"request", owner_token="new",
            created_at=CREATED, expires_at=EXPIRES, observed_at="2026-07-27T10:02:00Z",
        )
        assert replay.replayed is True
        assert replay.reservation.response == b"binary\x00response"
    finally:
        connection.close()
