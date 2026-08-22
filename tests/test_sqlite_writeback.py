import json
import sqlite3

import pytest

from reconforge.connectors.writeback import WritebackIntent, WritebackStatus, approve_writeback, dispatch_writeback
from reconforge.db.connection import DatabaseError, connect
from reconforge.db.migrations import run_migrations
from reconforge.infrastructure.sqlite_writeback import SQLiteWritebackIntentRepository, WritebackPersistenceError
from tests.test_connector_writeback import NOW, POLICY, _intent


def _insert_history_version(
    connection: sqlite3.Connection,
    *,
    intent: WritebackIntent,
    version: int,
    document: dict[str, object] | None = None,
) -> None:
    selected_document = intent.model_dump(mode="json", exclude_none=False) if document is None else document
    connection.execute(
        """
        INSERT INTO connector_writeback_intents(
            intent_id,tenant_id,workspace_id,version,status,intent_digest,intent_json,created_at
        ) VALUES(?,?,?,?,?,?,?,?)
        """,
        (
            intent.intent_id,
            intent.tenant_id,
            intent.workspace_id,
            version,
            intent.status.value,
            intent.digest,
            json.dumps(selected_document, sort_keys=True, separators=(",", ":"), ensure_ascii=True),
            intent.requested_at.isoformat(),
        ),
    )


def test_writeback_intent_history_is_idempotent_immutable_and_replayable(tmp_path) -> None:
    path = tmp_path / "writeback.db"
    run_migrations(path)
    connection = connect(path)
    repository = SQLiteWritebackIntentRepository(connection)
    proposed = _intent()
    assert repository.put(proposed) == proposed
    assert repository.put(proposed) == proposed
    approved = approve_writeback(
        proposed, policy=POLICY, actor_id="checker-1", approved_at=NOW, assurance="mfa", reason="reviewed"
    )
    assert repository.put(approved, expected_version=1) == approved
    dispatched = dispatch_writeback(approved, policy=POLICY)
    assert repository.put(dispatched, expected_version=2) == dispatched
    assert repository.put(dispatched, expected_version=3) == dispatched
    current = repository.get(intent_id=proposed.intent_id, tenant_id=proposed.tenant_id, workspace_id=proposed.workspace_id)
    assert current is not None and current["version"] == 3 and current["intent"].status is WritebackStatus.DISPATCHED
    assert len(repository.list_latest(tenant_id=proposed.tenant_id, workspace_id=proposed.workspace_id)) == 1
    with pytest.raises(WritebackPersistenceError, match="version conflict"):
        repository.put(dispatched.model_copy(update={"compensation_reason": "tampered"}), expected_version=1)
    with pytest.raises(sqlite3.IntegrityError, match="cannot be deleted"):
        connection.execute("DELETE FROM connector_writeback_intents").fetchall()


def test_writeback_intent_scope_isolation(tmp_path) -> None:
    path = tmp_path / "writeback-scope.db"
    run_migrations(path)
    connection = connect(path)
    repository = SQLiteWritebackIntentRepository(connection)
    proposed = _intent()
    repository.put(proposed)
    assert repository.get(intent_id=proposed.intent_id, tenant_id="other-tenant", workspace_id=proposed.workspace_id) is None


def test_repository_rejects_transition_that_retargets_the_original_proposal(tmp_path) -> None:
    path = tmp_path / "writeback-proposal-drift.db"
    run_migrations(path)
    connection = connect(path)
    repository = SQLiteWritebackIntentRepository(connection)
    proposed = _intent()
    repository.put(proposed)
    approved = approve_writeback(
        proposed,
        policy=POLICY,
        actor_id="checker-1",
        approved_at=NOW,
        assurance="mfa",
        reason="independent review",
    )

    with pytest.raises(WritebackPersistenceError, match="writeback_proposal_identity_immutable"):
        repository.put(approved.model_copy(update={"operation": "payment.update"}), expected_version=1)


def test_sqlite_guard_rejects_direct_proposal_drift_and_non_adjacent_transition(tmp_path) -> None:
    path = tmp_path / "writeback-direct-guard.db"
    run_migrations(path)
    connection = connect(path)
    repository = SQLiteWritebackIntentRepository(connection)
    proposed = _intent()
    repository.put(proposed)
    approved = approve_writeback(
        proposed,
        policy=POLICY,
        actor_id="checker-1",
        approved_at=NOW,
        assurance="mfa",
        reason="independent review",
    )

    missing_operation = approved.model_dump(mode="json", exclude_none=False)
    missing_operation.pop("operation")
    with pytest.raises(sqlite3.IntegrityError, match="fields are missing or invalid"):
        _insert_history_version(
            connection,
            intent=approved,
            version=2,
            document=missing_operation,
        )
    connection.rollback()

    with pytest.raises(sqlite3.IntegrityError, match="proposal identity is immutable"):
        _insert_history_version(
            connection,
            intent=approved.model_copy(update={"payload_digest": "f" * 64}),
            version=2,
        )
    connection.rollback()

    with pytest.raises(sqlite3.IntegrityError, match="transition is invalid"):
        _insert_history_version(
            connection,
            intent=dispatch_writeback(approved, policy=POLICY),
            version=2,
        )
    connection.rollback()


def test_sqlite_identity_migration_refuses_preexisting_drifted_history(tmp_path) -> None:
    path = tmp_path / "writeback-drifted-upgrade.db"
    status = run_migrations(path, target_version=41)
    assert status.current_version == 41
    connection = connect(path)
    repository = SQLiteWritebackIntentRepository(connection)
    proposed = _intent()
    repository.put(proposed)
    approved = approve_writeback(
        proposed,
        policy=POLICY,
        actor_id="checker-1",
        approved_at=NOW,
        assurance="mfa",
        reason="independent review",
    )
    _insert_history_version(
        connection,
        intent=approved.model_copy(update={"idempotency_key": "writeback-retargeted"}),
        version=2,
    )
    connection.commit()
    connection.close()

    with pytest.raises(DatabaseError, match="Unable to migrate ReconForge database"):
        run_migrations(path, target_version=42)

    verification = connect(path)
    applied = verification.execute("SELECT MAX(version) AS version FROM schema_migrations").fetchone()
    assert applied is not None and applied["version"] == 41


def test_sqlite_identity_migration_uses_temporary_audit_state(tmp_path) -> None:
    path = tmp_path / "writeback-migration-temp-state.db"
    run_migrations(path, target_version=41)
    connection = connect(path)
    connection.execute(
        "CREATE TABLE reconforge_writeback_identity_migration_check (sentinel TEXT NOT NULL)"
    )
    connection.execute(
        "INSERT INTO reconforge_writeback_identity_migration_check(sentinel) VALUES ('preserve-main-data')"
    )
    connection.commit()
    connection.close()

    status = run_migrations(path, target_version=42)

    assert status.current_version == 42
    verification = connect(path)
    row = verification.execute(
        "SELECT sentinel FROM reconforge_writeback_identity_migration_check"
    ).fetchone()
    assert row is not None and row["sentinel"] == "preserve-main-data"
