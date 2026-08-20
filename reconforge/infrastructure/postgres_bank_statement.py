"""Tenant/workspace-scoped PostgreSQL persistence for bank evidence.

The repository stores only bounded, replay-verifiable reports. It never
initiates payments, posts ledger entries, or performs provider I/O.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from reconforge.domain.bank_statement_control import BankStatementControlError, verify_bank_statement_payload
from reconforge.infrastructure.postgres import set_local_tenant_scope, validate_tenant_id, validate_workspace_id
from reconforge.io.persisted import (
    PersistedJsonError,
    decode_sqlite_bank_statement_control,
    encode_sqlite_bank_statement_control,
)

_ARTIFACT_TYPE = "reconforge-bank-statement-control"


class PostgresBankStatementPersistenceError(ValueError):
    """Safe persistence failure without source or financial-value disclosure."""


POSTGRES_BANK_STATEMENT_SCHEMA_SQL = r"""
CREATE TABLE IF NOT EXISTS reconforge.bank_statement_control_runs (
    tenant_id TEXT NOT NULL REFERENCES reconforge.tenants(id) ON DELETE CASCADE,
    workspace_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    decision_digest TEXT NOT NULL CHECK (decision_digest ~ '^[a-f0-9]{64}$'),
    artifact_digest TEXT NOT NULL CHECK (artifact_digest ~ '^[a-f0-9]{64}$'),
    algorithm_version TEXT NOT NULL CHECK (length(algorithm_version) BETWEEN 1 AND 128),
    status_counts JSONB NOT NULL CHECK (jsonb_typeof(status_counts) = 'object'),
    report_json JSONB NOT NULL CHECK (jsonb_typeof(report_json) = 'object'),
    prepared_by TEXT NOT NULL CHECK (length(prepared_by) BETWEEN 1 AND 256),
    prepared_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, workspace_id, run_id),
    UNIQUE (tenant_id, workspace_id, decision_digest),
    UNIQUE (tenant_id, workspace_id, artifact_digest)
);
CREATE INDEX IF NOT EXISTS bank_statement_control_runs_scope_idx
    ON reconforge.bank_statement_control_runs(tenant_id, workspace_id, created_at, run_id);
ALTER TABLE reconforge.bank_statement_control_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.bank_statement_control_runs FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_workspace_scope ON reconforge.bank_statement_control_runs;
CREATE POLICY tenant_workspace_scope ON reconforge.bank_statement_control_runs
    USING (tenant_id = current_setting('app.tenant_id', true)
        AND workspace_id = current_setting('app.workspace_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)
        AND workspace_id = current_setting('app.workspace_id', true));
CREATE OR REPLACE FUNCTION reconforge.guard_bank_statement_control_run()
RETURNS TRIGGER LANGUAGE plpgsql AS $reconforge$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION 'bank statement evidence is immutable' USING ERRCODE='check_violation';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'bank statement evidence cannot be deleted' USING ERRCODE='check_violation';
    END IF;
    RETURN NEW;
END
$reconforge$;
DROP TRIGGER IF EXISTS bank_statement_control_runs_guard ON reconforge.bank_statement_control_runs;
CREATE TRIGGER bank_statement_control_runs_guard
BEFORE UPDATE OR DELETE ON reconforge.bank_statement_control_runs
FOR EACH ROW EXECUTE FUNCTION reconforge.guard_bank_statement_control_run();
"""


def _artifact_digest(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _validate_payload(payload: Mapping[str, object]) -> None:
    if payload.get("artifact_type") != _ARTIFACT_TYPE:
        raise PostgresBankStatementPersistenceError("bank statement artifact type is invalid")
    digest = payload.get("artifact_digest")
    without_digest = {key: value for key, value in payload.items() if key != "artifact_digest"}
    if not isinstance(digest, str) or digest != _artifact_digest(without_digest):
        raise PostgresBankStatementPersistenceError("bank statement artifact digest mismatch")
    try:
        verify_bank_statement_payload(dict(payload))
    except (BankStatementControlError, KeyError, TypeError, ValueError) as exc:
        raise PostgresBankStatementPersistenceError("bank statement replay verification failed") from exc


def _row_value(row: Any, key: str, index: int) -> Any:
    return row.get(key) if isinstance(row, Mapping) else row[index]


class PostgresBankStatementRepository:
    """Persist immutable bank evidence under PostgreSQL tenant/workspace RLS."""

    def __init__(self, connection: Any) -> None:
        self.connection = connection

    @staticmethod
    def _scope(tenant_id: str, workspace_id: str) -> tuple[str, str]:
        tenant = validate_tenant_id(tenant_id)
        workspace = validate_workspace_id(workspace_id)
        if workspace is None:
            raise PostgresBankStatementPersistenceError("bank statement workspace scope is required")
        return tenant, workspace

    @staticmethod
    def _run_id(workspace_id: str, decision_digest: str) -> str:
        return f"bank-{workspace_id}-{decision_digest}"

    def put_payload(
        self,
        payload: Mapping[str, object],
        *,
        tenant_id: str,
        workspace_id: str,
        actor_label: str,
    ) -> dict[str, Any]:
        if not isinstance(payload, Mapping):
            raise PostgresBankStatementPersistenceError("bank statement report is invalid")
        payload_value = dict(payload)
        try:
            encoded = encode_sqlite_bank_statement_control(payload_value)
        except PersistedJsonError as exc:
            raise PostgresBankStatementPersistenceError("bank statement payload exceeds persistence bounds") from exc
        _validate_payload(payload_value)
        decision_digest = payload_value.get("decision_digest")
        artifact_digest = payload_value.get("artifact_digest")
        algorithm_version = payload_value.get("algorithm_version")
        status_counts = payload_value.get("status_counts")
        if (
            not isinstance(decision_digest, str)
            or not isinstance(artifact_digest, str)
            or not isinstance(algorithm_version, str)
        ):
            raise PostgresBankStatementPersistenceError("bank statement report identity is invalid")
        if not isinstance(status_counts, Mapping):
            raise PostgresBankStatementPersistenceError("bank statement status counts are invalid")
        actor = str(actor_label).strip()
        if not actor or len(actor) > 256:
            raise PostgresBankStatementPersistenceError("bank statement actor is invalid")
        try:
            tenant, workspace = self._scope(tenant_id, workspace_id)
            run_id = self._run_id(workspace, decision_digest)
            with self.connection.transaction():
                set_local_tenant_scope(self.connection, tenant, workspace_id=workspace)
                self.connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (f"bank-statement:{tenant}:{workspace}:{decision_digest}",),
                )
                self.connection.execute(
                    """
                    INSERT INTO reconforge.bank_statement_control_runs(
                        tenant_id, workspace_id, run_id, decision_digest, artifact_digest,
                        algorithm_version, status_counts, report_json, prepared_by,
                        prepared_at, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, now(), now())
                    ON CONFLICT (tenant_id, workspace_id, decision_digest) DO NOTHING
                    """,
                    (
                        tenant,
                        workspace,
                        run_id,
                        decision_digest,
                        artifact_digest,
                        algorithm_version,
                        json.dumps(dict(status_counts), sort_keys=True, separators=(",", ":"), ensure_ascii=True),
                        encoded.text,
                        actor,
                    ),
                )
                row = self.connection.execute(
                    """
                    SELECT tenant_id, workspace_id, run_id, decision_digest, artifact_digest,
                           algorithm_version, status_counts, report_json, prepared_by,
                           prepared_at, created_at
                    FROM reconforge.bank_statement_control_runs
                    WHERE tenant_id=%s AND workspace_id=%s AND decision_digest=%s
                    """,
                    (tenant, workspace, decision_digest),
                ).fetchone()
                if row is None:
                    raise PostgresBankStatementPersistenceError("bank statement persistence row is missing")
                result = self._row_to_public(row)
                if result["artifact_digest"] != artifact_digest:
                    raise PostgresBankStatementPersistenceError("bank statement id conflicts with a different artifact")
                return result
        except PostgresBankStatementPersistenceError:
            raise
        except Exception as exc:
            raise PostgresBankStatementPersistenceError("bank statement persistence failed") from exc

    def get(self, *, decision_digest: str, tenant_id: str, workspace_id: str) -> dict[str, Any] | None:
        try:
            tenant, workspace = self._scope(tenant_id, workspace_id)
            with self.connection.transaction():
                set_local_tenant_scope(self.connection, tenant, workspace_id=workspace)
                row = self.connection.execute(
                    """
                    SELECT tenant_id, workspace_id, run_id, decision_digest, artifact_digest,
                           algorithm_version, status_counts, report_json, prepared_by,
                           prepared_at, created_at
                    FROM reconforge.bank_statement_control_runs
                    WHERE tenant_id=%s AND workspace_id=%s AND decision_digest=%s
                    """,
                    (tenant, workspace, decision_digest),
                ).fetchone()
                return None if row is None else self._row_to_public(row)
        except PostgresBankStatementPersistenceError:
            raise
        except Exception as exc:
            raise PostgresBankStatementPersistenceError("bank statement read failed") from exc

    def list(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[dict[str, Any], ...]:
        if isinstance(limit, bool) or not 1 <= limit <= 500:
            raise PostgresBankStatementPersistenceError("bank statement list limit is invalid")
        if isinstance(offset, bool) or offset < 0:
            raise PostgresBankStatementPersistenceError("bank statement list offset is invalid")
        try:
            tenant, workspace = self._scope(tenant_id, workspace_id)
            with self.connection.transaction():
                set_local_tenant_scope(self.connection, tenant, workspace_id=workspace)
                rows = self.connection.execute(
                    """
                    SELECT tenant_id, workspace_id, run_id, decision_digest, artifact_digest,
                           algorithm_version, status_counts, report_json, prepared_by,
                           prepared_at, created_at
                    FROM reconforge.bank_statement_control_runs
                    WHERE tenant_id=%s AND workspace_id=%s
                    ORDER BY created_at, run_id
                    LIMIT %s OFFSET %s
                    """,
                    (tenant, workspace, limit, offset),
                ).fetchall()
                return tuple(self._row_to_public(row) for row in rows)
        except PostgresBankStatementPersistenceError:
            raise
        except Exception as exc:
            raise PostgresBankStatementPersistenceError("bank statement listing failed") from exc

    def _row_to_public(self, row: Any) -> dict[str, Any]:
        try:
            raw_report = _row_value(row, "report_json", 7)
            document = decode_sqlite_bank_statement_control(
                json.dumps(raw_report, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
                if isinstance(raw_report, Mapping)
                else str(raw_report)
            )
            payload = document.payload
            _validate_payload(payload)
            for column, index, message in (
                ("artifact_digest", 4, "artifact"),
                ("decision_digest", 3, "decision"),
                ("algorithm_version", 5, "algorithm"),
            ):
                if str(_row_value(row, column, index)) != str(payload.get(column)):
                    raise ValueError(f"{message} digest mismatch")
            stored_counts = _row_value(row, "status_counts", 6)
            if json.dumps(stored_counts, sort_keys=True, separators=(",", ":"), ensure_ascii=True) != json.dumps(
                payload.get("status_counts"), sort_keys=True, separators=(",", ":"), ensure_ascii=True
            ):
                raise ValueError("status counts mismatch")
            return {
                "id": str(_row_value(row, "run_id", 2)),
                "tenant_id": str(_row_value(row, "tenant_id", 0)),
                "workspace_id": str(_row_value(row, "workspace_id", 1)),
                "decision_digest": str(_row_value(row, "decision_digest", 3)),
                "artifact_digest": str(_row_value(row, "artifact_digest", 4)),
                "algorithm_version": str(_row_value(row, "algorithm_version", 5)),
                "prepared_by": str(_row_value(row, "prepared_by", 8)),
                "prepared_at": str(_row_value(row, "prepared_at", 9)),
                "created_at": str(_row_value(row, "created_at", 10)),
                "report": payload,
            }
        except PostgresBankStatementPersistenceError:
            raise
        except Exception as exc:
            raise PostgresBankStatementPersistenceError("bank statement persisted evidence is invalid") from exc


__all__ = [
    "POSTGRES_BANK_STATEMENT_SCHEMA_SQL",
    "PostgresBankStatementPersistenceError",
    "PostgresBankStatementRepository",
]
