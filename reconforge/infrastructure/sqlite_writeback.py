"""Immutable, tenant-scoped SQLite persistence for governed write-back intents."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from reconforge.connectors.writeback import (
    WritebackError,
    WritebackIntent,
    WritebackStatus,
    validate_writeback_transition,
)
from reconforge.connectors.writeback_network import WritebackRecoveryObservationRecord
from reconforge.platform.common import ensure_platform_schema


class WritebackPersistenceError(ValueError):
    """Safe persistence failure without payload or secret disclosure."""


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
            try:
                validate_writeback_transition(current["intent"], intent)
            except WritebackError as exc:
                raise WritebackPersistenceError(str(exc)) from exc
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
        if intent.digest != str(row["intent_digest"]) and intent.legacy_digest != str(row["intent_digest"]):
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


class SQLiteWritebackRecoveryObservationRepository:
    """Append-only, tenant-scoped persistence for provider-status observations."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        ensure_platform_schema(connection)
        self.connection = connection
        self._assert_schema()

    def _assert_schema(self) -> None:
        exists = self.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='connector_writeback_recovery_observations'"
        ).fetchone()
        if exists is None:
            raise WritebackPersistenceError("connector_writeback_recovery_observations migration is required")

    def _assert_intent_binding(self, record: WritebackRecoveryObservationRecord) -> None:
        row = self.connection.execute(
            """
            SELECT intent_json
            FROM connector_writeback_intents
            WHERE intent_id=? AND tenant_id=? AND workspace_id=?
            ORDER BY version DESC LIMIT 1
            """,
            (record.intent_id, record.tenant_id, record.workspace_id),
        ).fetchone()
        if row is None:
            raise WritebackPersistenceError("write-back recovery observation intent is not persisted")
        try:
            intent = WritebackIntent.model_validate(json.loads(str(row["intent_json"])))
        except Exception as exc:
            raise WritebackPersistenceError("persisted write-back recovery observation intent is invalid") from exc
        if (
            intent.connector_id != record.connector_id
            or intent.proposal_digest != record.proposal_digest
            or intent.idempotency_key != record.observation.idempotency_key
        ):
            raise WritebackPersistenceError("write-back recovery observation intent binding is invalid")

    @staticmethod
    def _decode(row: sqlite3.Row) -> WritebackRecoveryObservationRecord:
        try:
            record = WritebackRecoveryObservationRecord.model_validate(json.loads(str(row["observation_json"])))
            if (
                record.observation_id != str(row["observation_id"])
                or record.digest != str(row["observation_id"])
                or record.tenant_id != str(row["tenant_id"])
                or record.workspace_id != str(row["workspace_id"])
                or record.intent_id != str(row["intent_id"])
                or record.connector_id != str(row["connector_id"])
                or record.proposal_digest != str(row["proposal_digest"])
                or record.observation_digest != str(row["observation_digest"])
                or record.evidence_node_id != str(row["evidence_node_id"])
                or record.observed_by != str(row["observed_by"])
                or str(record.model_dump(mode="json")["observed_at"]) != str(row["observed_at"])
            ):
                raise ValueError("row identity mismatch")
            return record
        except Exception as exc:
            raise WritebackPersistenceError("persisted write-back recovery observation is invalid") from exc

    def put(self, record: WritebackRecoveryObservationRecord) -> WritebackRecoveryObservationRecord:
        if not isinstance(record, WritebackRecoveryObservationRecord):
            raise WritebackPersistenceError("write-back recovery observation is invalid")
        self._assert_intent_binding(record)
        existing = self.connection.execute(
            """
            SELECT * FROM connector_writeback_recovery_observations
            WHERE observation_id=? AND tenant_id=? AND workspace_id=?
            """,
            (record.observation_id, record.tenant_id, record.workspace_id),
        ).fetchone()
        if existing is not None:
            stored = self._decode(existing)
            if stored.digest == record.digest:
                return stored
            raise WritebackPersistenceError("write-back recovery observation identity conflict")
        try:
            self.connection.execute(
                """
                INSERT INTO connector_writeback_recovery_observations(
                    observation_id,tenant_id,workspace_id,intent_id,connector_id,
                    proposal_digest,observation_digest,evidence_node_id,observed_by,
                    observed_at,observation_json,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    record.observation_id,
                    record.tenant_id,
                    record.workspace_id,
                    record.intent_id,
                    record.connector_id,
                    record.proposal_digest,
                    record.observation_digest,
                    record.evidence_node_id,
                    record.observed_by,
                    str(record.model_dump(mode="json")["observed_at"]),
                    json.dumps(record.model_dump(mode="json", exclude_none=False), sort_keys=True, separators=(",", ":")),
                    str(record.model_dump(mode="json")["observed_at"]),
                ),
            )
            self.connection.commit()
        except sqlite3.IntegrityError as exc:
            self.connection.rollback()
            raise WritebackPersistenceError("write-back recovery observation persistence conflict") from exc
        return record

    def get(
        self,
        *,
        observation_id: str,
        tenant_id: str,
        workspace_id: str,
    ) -> WritebackRecoveryObservationRecord | None:
        row = self.connection.execute(
            """
            SELECT * FROM connector_writeback_recovery_observations
            WHERE observation_id=? AND tenant_id=? AND workspace_id=?
            """,
            (observation_id, tenant_id, workspace_id),
        ).fetchone()
        return None if row is None else self._decode(row)

    def list_for_intent(
        self,
        *,
        intent_id: str,
        tenant_id: str,
        workspace_id: str,
        limit: int = 100,
    ) -> tuple[WritebackRecoveryObservationRecord, ...]:
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 1_000:
            raise WritebackPersistenceError("write-back recovery observation limit is invalid")
        rows = self.connection.execute(
            """
            SELECT * FROM connector_writeback_recovery_observations
            WHERE intent_id=? AND tenant_id=? AND workspace_id=?
            ORDER BY observed_at, observation_id LIMIT ?
            """,
            (intent_id, tenant_id, workspace_id, limit),
        ).fetchall()
        return tuple(self._decode(row) for row in rows)
