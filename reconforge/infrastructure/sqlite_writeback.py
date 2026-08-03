"""Immutable, tenant-scoped SQLite persistence for governed write-back intents."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from reconforge.connectors.writeback import WritebackIntent, WritebackStatus
from reconforge.platform.common import ensure_platform_schema


class WritebackPersistenceError(ValueError):
    """Safe persistence failure without payload or secret disclosure."""


_TRANSITIONS: dict[WritebackStatus, frozenset[WritebackStatus]] = {
    WritebackStatus.PROPOSED: frozenset({WritebackStatus.APPROVED, WritebackStatus.REJECTED}),
    WritebackStatus.APPROVED: frozenset({WritebackStatus.DISPATCHED, WritebackStatus.REJECTED}),
    WritebackStatus.DISPATCHED: frozenset(
        {WritebackStatus.ACKNOWLEDGED, WritebackStatus.COMPENSATION_REQUESTED, WritebackStatus.FAILED}
    ),
    WritebackStatus.ACKNOWLEDGED: frozenset({WritebackStatus.COMPENSATION_REQUESTED}),
    WritebackStatus.COMPENSATION_REQUESTED: frozenset({WritebackStatus.COMPENSATED, WritebackStatus.FAILED}),
    WritebackStatus.COMPENSATED: frozenset(),
    WritebackStatus.REJECTED: frozenset(),
    WritebackStatus.FAILED: frozenset(),
}


class SQLiteWritebackIntentRepository:
    """Append-only intent history with idempotent replay and explicit scope."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        ensure_platform_schema(connection)
        self.connection = connection
        self._assert_schema()

    def _assert_schema(self) -> None:
        exists = self.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='connector_writeback_intents'"
        ).fetchone()
        if exists is None:
            raise WritebackPersistenceError("connector_writeback_intents migration is required")

    def put(
        self,
        intent: WritebackIntent,
        *,
        expected_version: int | None = None,
    ) -> WritebackIntent:
        if not isinstance(intent, WritebackIntent):
            raise WritebackPersistenceError("write-back intent is invalid")
        current = self.get(
            intent_id=intent.intent_id,
            tenant_id=intent.tenant_id,
            workspace_id=intent.workspace_id,
        )
        if current is not None:
            if current["intent"].digest == intent.digest:
                return current["intent"]
            if expected_version is None or current["version"] != expected_version:
                raise WritebackPersistenceError("write-back intent version conflict")
            if intent.status not in _TRANSITIONS[current["intent"].status]:
                raise WritebackPersistenceError("write-back intent transition is invalid")
            version = int(current["version"]) + 1
        else:
            if expected_version not in {None, 0} or intent.status is not WritebackStatus.PROPOSED:
                raise WritebackPersistenceError("write-back intent must start as proposed")
            version = 1
        document = intent.model_dump(mode="json", exclude_none=False)
        try:
            self.connection.execute(
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
                    json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True),
                    intent.requested_at.isoformat(),
                ),
            )
            self.connection.commit()
        except sqlite3.IntegrityError as exc:
            self.connection.rollback()
            raise WritebackPersistenceError("write-back intent persistence conflict") from exc
        return intent

    def get(self, *, intent_id: str, tenant_id: str, workspace_id: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            """
            SELECT version,status,intent_digest,intent_json
            FROM connector_writeback_intents
            WHERE intent_id=? AND tenant_id=? AND workspace_id=?
            ORDER BY version DESC LIMIT 1
            """,
            (intent_id, tenant_id, workspace_id),
        ).fetchone()
        if row is None:
            return None
        try:
            intent = WritebackIntent.model_validate(json.loads(str(row["intent_json"])))
        except Exception as exc:
            raise WritebackPersistenceError("persisted write-back intent is invalid") from exc
        if intent.digest != str(row["intent_digest"]):
            raise WritebackPersistenceError("persisted write-back intent digest mismatch")
        return {"version": int(row["version"]), "status": str(row["status"]), "intent": intent}

    def list_latest(self, *, tenant_id: str, workspace_id: str) -> tuple[WritebackIntent, ...]:
        rows = self.connection.execute(
            """
            SELECT intent_id, MAX(version) AS version
            FROM connector_writeback_intents
            WHERE tenant_id=? AND workspace_id=? GROUP BY intent_id ORDER BY intent_id
            """,
            (tenant_id, workspace_id),
        ).fetchall()
        result: list[WritebackIntent] = []
        for row in rows:
            current = self.get(intent_id=str(row["intent_id"]), tenant_id=tenant_id, workspace_id=workspace_id)
            if current is not None:
                result.append(current["intent"])
        return tuple(result)
