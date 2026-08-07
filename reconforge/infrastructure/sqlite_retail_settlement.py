"""Workspace-scoped immutable persistence for retail settlement evidence."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Mapping
from typing import Any

from reconforge.domain.models import utc_now_text
from reconforge.domain.retail_settlement import (
    RetailSettlementError,
    RetailSettlementRun,
    verify_retail_settlement_payload,
)
from reconforge.io.persisted import (
    PersistedJsonError,
    decode_sqlite_retail_settlement,
    encode_sqlite_retail_settlement,
)
from reconforge.platform.common import (
    PlatformError,
    commit_audited,
    ensure_platform_schema,
    ensure_workspace,
    platform_id,
    require_permission,
)


class RetailSettlementPersistenceError(ValueError):
    """Safe persistence failure without source or financial-value disclosure."""


_ARTIFACT_TYPE = "reconforge-retail-settlement"


def _artifact_digest(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _artifact_payload(run: RetailSettlementRun) -> dict[str, object]:
    payload = run.to_dict()
    payload["artifact_type"] = _ARTIFACT_TYPE
    payload["artifact_digest"] = _artifact_digest(payload)
    return payload


class SQLiteRetailSettlementRepository:
    """Persist one replay-verifiable retail run without posting or provider I/O."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        ensure_platform_schema(connection)
        self.connection = connection
        self._assert_schema()

    def _assert_schema(self) -> None:
        exists = self.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='retail_settlement_runs'",
        ).fetchone()
        if exists is None:
            raise RetailSettlementPersistenceError("retail settlement persistence migration is required")

    def _actor(self, actor_label: str) -> str:
        try:
            user = require_permission(
                self.connection,
                actor_label=actor_label,
                permission="finance_core.manage",
            )
        except PlatformError as exc:
            raise RetailSettlementPersistenceError("retail settlement actor is not authorized") from exc
        return user.username if user is not None else str(actor_label).strip()

    @staticmethod
    def _validate_payload(payload: Mapping[str, object]) -> None:
        if payload.get("artifact_type") != _ARTIFACT_TYPE:
            raise RetailSettlementPersistenceError("retail settlement artifact type is invalid")
        digest = payload.get("artifact_digest")
        without_digest = {key: value for key, value in payload.items() if key != "artifact_digest"}
        if not isinstance(digest, str) or digest != _artifact_digest(without_digest):
            raise RetailSettlementPersistenceError("retail settlement artifact digest mismatch")
        try:
            verify_retail_settlement_payload(payload)
        except (RetailSettlementError, KeyError, TypeError, ValueError) as exc:
            raise RetailSettlementPersistenceError("retail settlement replay verification failed") from exc

    def put(
        self,
        run: RetailSettlementRun,
        *,
        workspace: str = "default",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        if not isinstance(run, RetailSettlementRun):
            raise RetailSettlementPersistenceError("retail settlement run is invalid")
        actor = self._actor(actor_label)
        workspace_id = ensure_workspace(self.connection, workspace)
        payload = _artifact_payload(run)
        self._validate_payload(payload)
        try:
            encoded = encode_sqlite_retail_settlement(payload)
        except PersistedJsonError as exc:
            raise RetailSettlementPersistenceError("retail settlement payload exceeds persistence bounds") from exc
        run_id = platform_id("RTL", workspace_id, run.decision_digest)
        existing = self.connection.execute(
            "SELECT * FROM retail_settlement_runs WHERE id=?",
            (run_id,),
        ).fetchone()
        if existing is not None:
            if str(existing["artifact_digest"]) != str(payload["artifact_digest"]):
                raise RetailSettlementPersistenceError("retail settlement id conflicts with a different artifact")
            return self._row_to_public(existing)
        now = utc_now_text()
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            self.connection.execute(
                """
                INSERT INTO retail_settlement_runs(
                    id,workspace_id,decision_digest,artifact_digest,algorithm_version,
                    status_counts_json,payload_json,prepared_by,prepared_at,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    run_id,
                    workspace_id,
                    run.decision_digest,
                    str(payload["artifact_digest"]),
                    run.algorithm_version,
                    json.dumps(run.status_counts, sort_keys=True, separators=(",", ":"), ensure_ascii=True),
                    encoded.text,
                    actor,
                    now,
                    now,
                ),
            )
            commit_audited(
                self.connection,
                actor_label=actor,
                object_type="retail_settlement_run",
                object_id=run_id,
                action="retail_settlement_persisted",
                metadata={
                    "workspace_id": workspace_id,
                    "decision_digest": run.decision_digest,
                    "artifact_digest": str(payload["artifact_digest"]),
                },
            )
        except sqlite3.IntegrityError as exc:
            self.connection.rollback()
            raced = self.connection.execute(
                "SELECT * FROM retail_settlement_runs WHERE id=?",
                (run_id,),
            ).fetchone()
            if raced is not None:
                if str(raced["artifact_digest"]) == str(payload["artifact_digest"]):
                    return self._row_to_public(raced)
                raise RetailSettlementPersistenceError(
                    "retail settlement id conflicts with a different artifact"
                ) from exc
            raise RetailSettlementPersistenceError("retail settlement persistence failed") from exc
        except (PlatformError, sqlite3.DatabaseError) as exc:
            self.connection.rollback()
            raise RetailSettlementPersistenceError("retail settlement persistence failed") from exc
        return self._row_to_public(self.connection.execute("SELECT * FROM retail_settlement_runs WHERE id=?", (run_id,)).fetchone())

    def get(self, *, decision_digest: str, workspace: str = "default") -> dict[str, Any] | None:
        workspace_id = ensure_workspace(self.connection, workspace)
        row = self.connection.execute(
            "SELECT * FROM retail_settlement_runs WHERE workspace_id=? AND decision_digest=?",
            (workspace_id, decision_digest),
        ).fetchone()
        return None if row is None else self._row_to_public(row)

    def list(self, *, workspace: str = "default") -> tuple[dict[str, Any], ...]:
        workspace_id = ensure_workspace(self.connection, workspace)
        rows = self.connection.execute(
            "SELECT * FROM retail_settlement_runs WHERE workspace_id=? ORDER BY created_at,id",
            (workspace_id,),
        ).fetchall()
        return tuple(self._row_to_public(row) for row in rows)

    def _row_to_public(self, row: sqlite3.Row | None) -> dict[str, Any]:
        if row is None:
            raise RetailSettlementPersistenceError("retail settlement persistence row is missing")
        try:
            document = decode_sqlite_retail_settlement(str(row["payload_json"]))
        except PersistedJsonError as exc:
            raise RetailSettlementPersistenceError("retail settlement persisted JSON is invalid") from exc
        payload = document.payload
        self._validate_payload(payload)
        if str(row["artifact_digest"]) != str(payload.get("artifact_digest")):
            raise RetailSettlementPersistenceError("retail settlement persisted digest mismatch")
        if str(row["decision_digest"]) != str(payload.get("decision_digest")):
            raise RetailSettlementPersistenceError("retail settlement persisted decision mismatch")
        if str(row["algorithm_version"]) != str(payload.get("algorithm_version")):
            raise RetailSettlementPersistenceError("retail settlement persisted algorithm mismatch")
        expected_status_counts = json.dumps(
            payload.get("status_counts"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        if str(row["status_counts_json"]) != expected_status_counts:
            raise RetailSettlementPersistenceError("retail settlement persisted status mismatch")
        return {
            "id": str(row["id"]),
            "workspace_id": str(row["workspace_id"]),
            "decision_digest": str(row["decision_digest"]),
            "artifact_digest": str(row["artifact_digest"]),
            "algorithm_version": str(row["algorithm_version"]),
            "prepared_by": str(row["prepared_by"]),
            "prepared_at": str(row["prepared_at"]),
            "created_at": str(row["created_at"]),
            "report": payload,
        }


__all__ = ["RetailSettlementPersistenceError", "SQLiteRetailSettlementRepository"]
