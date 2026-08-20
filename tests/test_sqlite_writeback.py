import sqlite3

import pytest

from reconforge.connectors.writeback import WritebackStatus, approve_writeback, dispatch_writeback
from reconforge.db.connection import connect
from reconforge.db.migrations import run_migrations
from reconforge.infrastructure.sqlite_writeback import SQLiteWritebackIntentRepository, WritebackPersistenceError
from tests.test_connector_writeback import NOW, POLICY, _intent


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
