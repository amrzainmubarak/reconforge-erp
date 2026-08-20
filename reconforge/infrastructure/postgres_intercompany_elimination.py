"""Tenant/workspace-scoped PostgreSQL persistence for intercompany proposals."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any

from reconforge.domain.consolidation import ConsolidationError
from reconforge.domain.intercompany_elimination import (
    IntercompanyEliminationInputLine,
    IntercompanyEliminationResult,
    intercompany_elimination_input_line_from_dict,
    verify_intercompany_elimination_payload,
)
from reconforge.infrastructure.postgres import set_local_tenant_scope, validate_tenant_id
from reconforge.infrastructure.postgres_domain import PostgresAuditEventRepository
from reconforge.platform.common import PlatformError, normalize_text

POSTGRES_INTERCOMPANY_ELIMINATION_SCHEMA_SQL = r"""
CREATE TABLE IF NOT EXISTS reconforge.intercompany_elimination_artifacts (
    tenant_id TEXT NOT NULL,
    id TEXT NOT NULL CHECK (id ~ '^ice-[0-9a-f]{32}$'),
    workspace_id TEXT NOT NULL,
    reporting_currency TEXT NOT NULL CHECK (reporting_currency ~ '^[A-Z][A-Z0-9]{2,5}$'),
    version TEXT NOT NULL CHECK (version ~ '^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$'),
    request_digest TEXT NOT NULL CHECK (request_digest ~ '^[a-f0-9]{64}$'),
    result_digest TEXT NOT NULL CHECK (result_digest ~ '^[a-f0-9]{64}$'),
    request_payload JSONB NOT NULL CHECK (jsonb_typeof(request_payload) = 'object'),
    result_payload JSONB NOT NULL CHECK (jsonb_typeof(result_payload) = 'object'),
    prepared_by TEXT NOT NULL,
    prepared_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, workspace_id, result_digest),
    FOREIGN KEY (tenant_id, workspace_id)
        REFERENCES reconforge.domain_workspaces(tenant_id, id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id, prepared_by)
        REFERENCES reconforge.identity_users(tenant_id, id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS intercompany_elimination_scope_idx
    ON reconforge.intercompany_elimination_artifacts
        (tenant_id, workspace_id, reporting_currency, created_at, id);
ALTER TABLE reconforge.intercompany_elimination_artifacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.intercompany_elimination_artifacts FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.intercompany_elimination_artifacts;
CREATE POLICY tenant_scope ON reconforge.intercompany_elimination_artifacts
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
CREATE OR REPLACE FUNCTION reconforge.guard_intercompany_elimination_artifact()
RETURNS TRIGGER LANGUAGE plpgsql AS $reconforge$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION 'intercompany elimination artifacts are immutable' USING ERRCODE='check_violation';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'intercompany elimination artifacts cannot be deleted' USING ERRCODE='check_violation';
    END IF;
    RETURN NEW;
END
$reconforge$;
DROP TRIGGER IF EXISTS intercompany_elimination_artifact_guard
    ON reconforge.intercompany_elimination_artifacts;
CREATE TRIGGER intercompany_elimination_artifact_guard
BEFORE UPDATE OR DELETE ON reconforge.intercompany_elimination_artifacts
FOR EACH ROW EXECUTE FUNCTION reconforge.guard_intercompany_elimination_artifact();
"""


class PostgresIntercompanyEliminationError(RuntimeError):
    """Safe PostgreSQL intercompany-elimination persistence failure."""


def _row_value(row: Any, key: str, index: int) -> Any:
    return row.get(key) if isinstance(row, Mapping) else row[index]


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _payload(value: object, field: str) -> dict[str, object]:
    try:
        decoded = json.loads(value) if isinstance(value, str) else value
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise PostgresIntercompanyEliminationError(f"Persisted intercompany {field} is invalid.") from exc
    if not isinstance(decoded, dict):
        raise PostgresIntercompanyEliminationError(f"Persisted intercompany {field} is invalid.")
    return dict(decoded)


def _source_lines(payload: Mapping[str, object]) -> tuple[IntercompanyEliminationInputLine, ...]:
    if set(payload) != {"lines", "prepared_at", "prepared_by", "reporting_currency", "version"}:
        raise PostgresIntercompanyEliminationError("Persisted intercompany request fields are not exact.")
    raw_lines = payload["lines"]
    if not isinstance(raw_lines, list):
        raise PostgresIntercompanyEliminationError("Persisted intercompany source lines are invalid.")
    try:
        return tuple(intercompany_elimination_input_line_from_dict(item) for item in raw_lines)
    except (ConsolidationError, TypeError, ValueError) as exc:
        raise PostgresIntercompanyEliminationError("Persisted intercompany source lines failed decoding.") from exc


class PostgresIntercompanyEliminationRepository:
    """Persist replay-verified proposals; no journal posting is exposed here."""

    def __init__(self, connection: Any, tenant_id: str) -> None:
        self.connection = connection
        self.tenant_id = validate_tenant_id(tenant_id)

    @staticmethod
    def _actor(value: str) -> str:
        actor = normalize_text(value, default="")
        if not actor:
            raise PlatformError("Intercompany elimination actor is required.")
        return actor

    @staticmethod
    def _workspace(value: str) -> str:
        workspace = normalize_text(value, default="")
        if not workspace:
            raise PlatformError("Intercompany elimination workspace is required.")
        return workspace

    def _scope(self) -> None:
        set_local_tenant_scope(self.connection, self.tenant_id)

    def _artifact_id(self, workspace: str, result: IntercompanyEliminationResult) -> str:
        digest = hashlib.sha256(f"{self.tenant_id}|{workspace}|{result.request_digest}".encode("ascii")).hexdigest()
        return f"ice-{digest[:32]}"

    @staticmethod
    def _verify_result(
        lines: tuple[IntercompanyEliminationInputLine, ...],
        result: IntercompanyEliminationResult,
    ) -> dict[str, object]:
        if not isinstance(result, IntercompanyEliminationResult):
            raise PostgresIntercompanyEliminationError("A typed intercompany elimination result is required.")
        try:
            replay = verify_intercompany_elimination_payload(result.to_dict(), lines)
        except (ConsolidationError, TypeError, ValueError) as exc:
            raise PostgresIntercompanyEliminationError(
                "Intercompany elimination evidence failed deterministic replay verification."
            ) from exc
        if replay.result_digest != result.result_digest:
            raise PostgresIntercompanyEliminationError("Intercompany result digest lineage is invalid.")
        return result.to_dict()

    @classmethod
    def _decode_row(cls, row: Any) -> dict[str, Any]:
        request_payload = _payload(_row_value(row, "request_payload", 7), "request payload")
        result_payload = _payload(_row_value(row, "result_payload", 8), "result payload")
        lines = _source_lines(request_payload)
        try:
            replay = verify_intercompany_elimination_payload(result_payload, lines)
        except (ConsolidationError, TypeError, ValueError) as exc:
            raise PostgresIntercompanyEliminationError("Persisted intercompany evidence failed replay verification.") from exc
        if str(_row_value(row, "request_digest", 5)) != replay.request_digest or str(_row_value(row, "result_digest", 6)) != replay.result_digest:
            raise PostgresIntercompanyEliminationError("Persisted intercompany digest columns do not match payloads.")
        return {
            "id": str(_row_value(row, "id", 1)),
            "tenant_id": str(_row_value(row, "tenant_id", 0)),
            "workspace_id": str(_row_value(row, "workspace_id", 2)),
            "reporting_currency": str(_row_value(row, "reporting_currency", 3)),
            "version": str(_row_value(row, "version", 4)),
            "request_digest": replay.request_digest,
            "result_digest": replay.result_digest,
            "request_payload": request_payload,
            "result_payload": result_payload,
            "prepared_by": str(_row_value(row, "prepared_by", 9)),
            "prepared_at": str(_row_value(row, "prepared_at", 10)),
            "created_at": str(_row_value(row, "created_at", 11)),
            "posting": "not_available",
        }

    def persist(
        self,
        lines: tuple[IntercompanyEliminationInputLine, ...],
        result: IntercompanyEliminationResult,
        *,
        workspace: str,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        actor = self._actor(actor_label)
        workspace_id = self._workspace(workspace)
        if actor != result.prepared_by:
            raise PlatformError("The authenticated intercompany preparer must match the result preparer.")
        payload = self._verify_result(lines, result)
        request_payload: dict[str, object] = {
            "lines": [line.to_dict() for line in sorted(lines, key=lambda item: item.transaction_id)],
            "prepared_at": result.prepared_at,
            "prepared_by": result.prepared_by,
            "reporting_currency": result.reporting_currency,
            "version": result.version,
        }
        identifier = self._artifact_id(workspace_id, result)
        if re.fullmatch(r"ice-[0-9a-f]{32}", identifier) is None:
            raise PlatformError("Intercompany elimination artifact ID is invalid.")
        try:
            with self.connection.transaction():
                self._scope()
                existing = self.connection.execute(
                    "SELECT * FROM reconforge.intercompany_elimination_artifacts WHERE tenant_id=%s AND id=%s",
                    (self.tenant_id, identifier),
                ).fetchone()
                if existing is not None:
                    stored = self._decode_row(existing)
                    if stored["request_digest"] != result.request_digest or stored["result_digest"] != result.result_digest:
                        raise PlatformError("Intercompany artifact identifier conflicts with immutable evidence.")
                    return stored
                self.connection.execute(
                    """INSERT INTO reconforge.intercompany_elimination_artifacts(
                         tenant_id,id,workspace_id,reporting_currency,version,request_digest,result_digest,
                         request_payload,result_payload,prepared_by,prepared_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,CAST(%s AS jsonb),CAST(%s AS jsonb),%s,%s)""",
                    (
                        self.tenant_id,
                        identifier,
                        workspace_id,
                        result.reporting_currency,
                        result.version,
                        result.request_digest,
                        result.result_digest,
                        _json(request_payload),
                        _json(payload),
                        result.prepared_by,
                        result.prepared_at,
                    ),
                )
                PostgresAuditEventRepository(self.connection, self.tenant_id).append(
                    actor_label=actor,
                    actor_user_id=actor,
                    object_type="intercompany_elimination_artifact",
                    object_id=identifier,
                    action="intercompany_elimination_artifact_created",
                    after_hash=result.result_digest,
                    metadata={
                        "workspace_id": workspace_id,
                        "reporting_currency": result.reporting_currency,
                        "proposal_count": sum(item.status == "proposed" for item in result.resolutions),
                        "unresolved_count": sum(item.status == "unresolved" for item in result.resolutions),
                        "posting": "not_available",
                    },
                )
                return {
                    "id": identifier,
                    "tenant_id": self.tenant_id,
                    "workspace_id": workspace_id,
                    "request_digest": result.request_digest,
                    "result_digest": result.result_digest,
                    "posting": "not_available",
                }
        except (PlatformError, PostgresIntercompanyEliminationError):
            raise
        except Exception as exc:
            raise PostgresIntercompanyEliminationError("PostgreSQL intercompany elimination persistence failed.") from exc

    def get(self, artifact_id: str, *, actor_label: str = "local-cli") -> dict[str, Any]:
        self._actor(actor_label)
        if re.fullmatch(r"ice-[0-9a-f]{32}", artifact_id) is None:
            raise PlatformError("Intercompany elimination artifact ID is invalid.")
        try:
            with self.connection.transaction():
                self._scope()
                row = self.connection.execute(
                    "SELECT * FROM reconforge.intercompany_elimination_artifacts WHERE tenant_id=%s AND id=%s",
                    (self.tenant_id, artifact_id),
                ).fetchone()
                if row is None:
                    raise PostgresIntercompanyEliminationError("Intercompany elimination artifact was not found.")
                return self._decode_row(row)
        except (PlatformError, PostgresIntercompanyEliminationError):
            raise
        except Exception as exc:
            raise PostgresIntercompanyEliminationError("PostgreSQL intercompany elimination read failed.") from exc


__all__ = [
    "POSTGRES_INTERCOMPANY_ELIMINATION_SCHEMA_SQL",
    "PostgresIntercompanyEliminationError",
    "PostgresIntercompanyEliminationRepository",
]
