"""Durable provider-status observation contracts and SQLite enforcement."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from reconforge.connectors.writeback_network import (
    WritebackProviderOutcome,
    WritebackRecoveryObservation,
    WritebackRecoveryObservationRecord,
)
from reconforge.db import connect, run_migrations
from reconforge.infrastructure.sqlite_writeback import (
    SQLiteWritebackIntentRepository,
    SQLiteWritebackRecoveryObservationRepository,
    WritebackPersistenceError,
)
from tests.test_connector_writeback import _intent

OBSERVED_AT = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)


def _observation(
    *,
    outcome: WritebackProviderOutcome = WritebackProviderOutcome.PENDING,
    key: str = "writeback-001",
) -> WritebackRecoveryObservation:
    return WritebackRecoveryObservation(
        outcome=outcome,
        idempotency_key=key,
        http_status=202 if outcome is WritebackProviderOutcome.PENDING else 200,
        body_digest="a" * 64,
        provider_reference="provider-accepted" if outcome is WritebackProviderOutcome.ACCEPTED else None,
        provider_response_digest="b" * 64 if outcome is WritebackProviderOutcome.ACCEPTED else None,
    )


def _open_repositories(path: Path) -> tuple[sqlite3.Connection, SQLiteWritebackRecoveryObservationRepository]:
    run_migrations(path)
    connection = connect(path)
    SQLiteWritebackIntentRepository(connection).put(_intent())
    return connection, SQLiteWritebackRecoveryObservationRepository(connection)


def test_sqlite_observation_is_append_only_scoped_and_idempotent(tmp_path: Path) -> None:
    connection, repository = _open_repositories(tmp_path / "observations.db")
    try:
        record = WritebackRecoveryObservationRecord.for_intent(
            _intent(),
            _observation(),
            observed_by="checker-1",
            observed_at=OBSERVED_AT,
        )
        assert repository.put(record) == record
        assert repository.put(record) == record
        assert repository.get(
            observation_id=record.observation_id or "",
            tenant_id="tenant-a",
            workspace_id="workspace-a",
        ) == record
        assert repository.list_for_intent(
            intent_id="intent-001",
            tenant_id="tenant-a",
            workspace_id="workspace-a",
        ) == (record,)
        assert connection.execute(
            "SELECT COUNT(*) FROM connector_writeback_recovery_observations"
        ).fetchone()[0] == 1
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                "UPDATE connector_writeback_recovery_observations SET observed_by=?",
                ("attacker",),
            )
        with pytest.raises(sqlite3.IntegrityError, match="cannot be deleted"):
            connection.execute("DELETE FROM connector_writeback_recovery_observations")
    finally:
        connection.close()


@pytest.mark.parametrize(
    "outcome",
    [
        WritebackProviderOutcome.REJECTED,
        WritebackProviderOutcome.PENDING,
        WritebackProviderOutcome.NOT_FOUND,
        WritebackProviderOutcome.UNKNOWN,
    ],
)
def test_sqlite_observation_persists_nonaccepted_outcomes_without_intent_mutation(
    tmp_path: Path,
    outcome: WritebackProviderOutcome,
) -> None:
    connection, repository = _open_repositories(tmp_path / f"{outcome.value}.db")
    try:
        intent = SQLiteWritebackIntentRepository(connection).get(
            intent_id="intent-001", tenant_id="tenant-a", workspace_id="workspace-a"
        )
        assert intent is not None
        record = WritebackRecoveryObservationRecord.for_intent(
            intent["intent"],
            _observation(outcome=outcome),
            observed_by="system-recovery",
            observed_at=OBSERVED_AT,
        )
        repository.put(record)
        current = SQLiteWritebackIntentRepository(connection).get(
            intent_id="intent-001", tenant_id="tenant-a", workspace_id="workspace-a"
        )
        assert current is not None
        assert current["intent"].status.value == "proposed"
    finally:
        connection.close()


def test_observation_binding_rejects_retargeting_and_unknown_intent(tmp_path: Path) -> None:
    connection, repository = _open_repositories(tmp_path / "binding.db")
    try:
        intent = _intent()
        record = WritebackRecoveryObservationRecord.for_intent(
            intent,
            _observation(),
            observed_by="checker-1",
            observed_at=OBSERVED_AT,
        )
        with pytest.raises(WritebackPersistenceError, match="binding"):
            repository.put(record.model_copy(update={"proposal_digest": "f" * 64}))
        with pytest.raises(WritebackPersistenceError, match="intent is not persisted"):
            repository.put(
                WritebackRecoveryObservationRecord.for_intent(
                    intent.model_copy(update={"intent_id": "missing-intent"}),
                    _observation(),
                    observed_by="checker-1",
                    observed_at=OBSERVED_AT,
                )
            )
        with pytest.raises(WritebackPersistenceError, match="limit"):
            repository.list_for_intent(
                intent_id=intent.intent_id,
                tenant_id=intent.tenant_id,
                workspace_id=intent.workspace_id,
                limit=0,
            )
    finally:
        connection.close()


def test_observation_migration_is_additive_from_previous_sqlite_version(tmp_path: Path) -> None:
    path = tmp_path / "upgrade.db"
    assert run_migrations(path, target_version=42).current_version == 42
    upgraded = run_migrations(path)
    assert upgraded.current_version == upgraded.latest_version == 43
    connection = connect(path)
    try:
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='connector_writeback_recovery_observations'"
        ).fetchone() is not None
    finally:
        connection.close()
