"""Tenant/workspace-scoped PostgreSQL persistence for professional invoice/payment evidence.

The repository stores only a bounded, replay-verifiable report. It never
posts to providers, performs network calls, or executes financial writes.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from reconforge.domain.professional_invoice_payment_control import (
    ProfessionalInvoicePaymentError,
    verify_professional_invoice_payment_payload,
)
from reconforge.infrastructure.postgres import set_local_tenant_scope, validate_tenant_id, validate_workspace_id
from reconforge.io.persisted import (
    PersistedJsonError,
    decode_sqlite_professional_invoice_payment,
    encode_sqlite_professional_invoice_payment,
)

_ARTIFACT_TYPE = "reconforge-professional-invoice-payment-control"


class PostgresProfessionalInvoicePaymentPersistenceError(ValueError):
    """Safe persistence failure without source or financial-value disclosure."""


POSTGRES_PROFESSIONAL_INVOICE_PAYMENT_SCHEMA_SQL = r"""
CREATE TABLE IF NOT EXISTS reconforge.professional_invoice_payment_runs (
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
    UNIQUE (tenant_id, workspace_id, decision_digest)
);
CREATE INDEX IF NOT EXISTS professional_invoice_payment_runs_scope_idx
    ON reconforge.professional_invoice_payment_runs(tenant_id, workspace_id, created_at, run_id);
ALTER TABLE reconforge.professional_invoice_payment_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.professional_invoice_payment_runs FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_workspace_scope ON reconforge.professional_invoice_payment_runs;
CREATE POLICY tenant_workspace_scope ON reconforge.professional_invoice_payment_runs
    USING (
        tenant_id = current_setting('app.tenant_id', true)
        AND workspace_id = current_setting('app.workspace_id', true)
    )
    WITH CHECK (
        tenant_id = current_setting('app.tenant_id', true)
        AND workspace_id = current_setting('app.workspace_id', true)
    );
CREATE OR REPLACE FUNCTION reconforge.guard_professional_invoice_payment_run()
RETURNS TRIGGER LANGUAGE plpgsql AS $reconforge$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION 'professional invoice/payment evidence is immutable' USING ERRCODE='check_violation';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'professional invoice/payment evidence cannot be deleted' USING ERRCODE='check_violation';
    END IF;
    RETURN NEW;
END
$reconforge$;
DROP TRIGGER IF EXISTS professional_invoice_payment_runs_guard
    ON reconforge.professional_invoice_payment_runs;
CREATE TRIGGER professional_invoice_payment_runs_guard
BEFORE UPDATE OR DELETE ON reconforge.professional_invoice_payment_runs
FOR EACH ROW EXECUTE FUNCTION reconforge.guard_professional_invoice_payment_run();
"""


def _artifact_digest(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _validate_payload(payload: Mapping[str, object]) -> None:
    if payload.get("artifact_type") != _ARTIFACT_TYPE:
        raise PostgresProfessionalInvoicePaymentPersistenceError("professional invoice/payment artifact type is invalid")
    digest = payload.get("artifact_digest")
    without_digest = {key: value for key, value in payload.items() if key != "artifact_digest"}
    if not isinstance(digest, str) or digest != _artifact_digest(without_digest):
        raise PostgresProfessionalInvoicePaymentPersistenceError(
            "professional invoice/payment artifact digest mismatch"
        )
    try:
        verify_professional_invoice_payment_payload(dict(payload))
    except (ProfessionalInvoicePaymentError, KeyError, TypeError, ValueError) as exc:
        raise PostgresProfessionalInvoicePaymentPersistenceError(
            "professional invoice/payment replay verification failed"
        ) from exc


def _row_value(row: Any, key: str, index: int) -> Any:
    return row.get(key) if isinstance(row, Mapping) else row[index]


class PostgresProfessionalInvoicePaymentRepository:
    """Persist immutable professional evidence under PostgreSQL tenant/workspace RLS."""

    def __init__(self, connection: Any) -> None:
        self.connection = connection

    @staticmethod
    def _scope(tenant_id: str, workspace_id: str) -> tuple[str, str]:
        tenant = validate_tenant_id(tenant_id)
        workspace = validate_workspace_id(workspace_id)
        if workspace is None:
            raise PostgresProfessionalInvoicePaymentPersistenceError("professional invoice/payment workspace scope is required")
        return tenant, workspace

    @staticmethod
    def _run_id(workspace_id: str, decision_digest: str) -> str:
        return f"pip-{workspace_id}-{decision_digest}"

    def put_payload(
        self,
        payload: Mapping[str, object],
        *,
        tenant_id: str,
        workspace_id: str,
        actor_label: str,
    ) -> dict[str, Any]:
        """Persist one bounded report with idempotent digest replay."""

        if not isinstance(payload, Mapping):
            raise PostgresProfessionalInvoicePaymentPersistenceError("professional invoice/payment report is invalid")
        payload_value = dict(payload)
        try:
            encoded = encode_sqlite_professional_invoice_payment(payload_value)
        except PersistedJsonError as exc:
            raise PostgresProfessionalInvoicePaymentPersistenceError(
                "professional invoice/payment payload exceeds persistence bounds"
            ) from exc
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
            raise PostgresProfessionalInvoicePaymentPersistenceError(
                "professional invoice/payment report identity is invalid"
            )
        if not isinstance(status_counts, Mapping):
            raise PostgresProfessionalInvoicePaymentPersistenceError(
                "professional invoice/payment report status counts are invalid"
            )
        actor = str(actor_label).strip()
        if not actor or len(actor) > 256:
            raise PostgresProfessionalInvoicePaymentPersistenceError("professional invoice/payment actor is invalid")
        try:
            tenant, workspace = self._scope(tenant_id, workspace_id)
            run_id = self._run_id(workspace, decision_digest)
            with self.connection.transaction():
                set_local_tenant_scope(self.connection, tenant, workspace_id=workspace)
                self.connection.execute(
                    """
                    SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))
                    """,
                    (f"professional-invoice-payment:{tenant}:{workspace}:{decision_digest}",),
                )
                self.connection.execute(
                    """
                    INSERT INTO reconforge.professional_invoice_payment_runs(
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
                    FROM reconforge.professional_invoice_payment_runs
                    WHERE tenant_id=%s AND workspace_id=%s AND decision_digest=%s
                    """,
                    (tenant, workspace, decision_digest),
                ).fetchone()
                if row is None:
                    raise PostgresProfessionalInvoicePaymentPersistenceError(
                        "professional invoice/payment persistence row is missing"
                    )
                result = self._row_to_public(row)
                if result["artifact_digest"] != artifact_digest:
                    raise PostgresProfessionalInvoicePaymentPersistenceError(
                        "professional invoice/payment id conflicts with a different artifact"
                    )
                return result
        except PostgresProfessionalInvoicePaymentPersistenceError:
            raise
        except Exception as exc:
            raise PostgresProfessionalInvoicePaymentPersistenceError("professional invoice/payment persistence failed") from exc

    def get(
        self,
        *,
        decision_digest: str,
        tenant_id: str,
        workspace_id: str,
    ) -> dict[str, Any] | None:
        try:
            tenant, workspace = self._scope(tenant_id, workspace_id)
            with self.connection.transaction():
                set_local_tenant_scope(self.connection, tenant, workspace_id=workspace)
                row = self.connection.execute(
                    """
                    SELECT tenant_id, workspace_id, run_id, decision_digest, artifact_digest,
                           algorithm_version, status_counts, report_json, prepared_by,
                           prepared_at, created_at
                    FROM reconforge.professional_invoice_payment_runs
                    WHERE tenant_id=%s AND workspace_id=%s AND decision_digest=%s
                    """,
                    (tenant, workspace, decision_digest),
                ).fetchone()
                return None if row is None else self._row_to_public(row)
        except PostgresProfessionalInvoicePaymentPersistenceError:
            raise
        except Exception as exc:
            raise PostgresProfessionalInvoicePaymentPersistenceError("professional invoice/payment read failed") from exc

    def list(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[dict[str, Any], ...]:
        if isinstance(limit, bool) or not 1 <= limit <= 500:
            raise PostgresProfessionalInvoicePaymentPersistenceError("professional invoice/payment list limit is invalid")
        if isinstance(offset, bool) or offset < 0:
            raise PostgresProfessionalInvoicePaymentPersistenceError("professional invoice/payment list offset is invalid")
        try:
            tenant, workspace = self._scope(tenant_id, workspace_id)
            with self.connection.transaction():
                set_local_tenant_scope(self.connection, tenant, workspace_id=workspace)
                rows = self.connection.execute(
                    """
                    SELECT tenant_id, workspace_id, run_id, decision_digest, artifact_digest,
                           algorithm_version, status_counts, report_json, prepared_by,
                           prepared_at, created_at
                    FROM reconforge.professional_invoice_payment_runs
                    WHERE tenant_id=%s AND workspace_id=%s
                    ORDER BY created_at, run_id
                    LIMIT %s OFFSET %s
                    """,
                    (tenant, workspace, limit, offset),
                ).fetchall()
                return tuple(self._row_to_public(row) for row in rows)
        except PostgresProfessionalInvoicePaymentPersistenceError:
            raise
        except Exception as exc:
            raise PostgresProfessionalInvoicePaymentPersistenceError("professional invoice/payment listing failed") from exc

    def _row_to_public(self, row: Any) -> dict[str, Any]:
        try:
            raw_report = _row_value(row, "report_json", 7)
            document = decode_sqlite_professional_invoice_payment(
                json.dumps(raw_report, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
                if isinstance(raw_report, Mapping)
                else str(raw_report)
            )
            payload = document.payload
            _validate_payload(payload)
            if str(_row_value(row, "artifact_digest", 4)) != str(payload.get("artifact_digest")):
                raise ValueError("artifact digest mismatch")
            if str(_row_value(row, "decision_digest", 3)) != str(payload.get("decision_digest")):
                raise ValueError("decision digest mismatch")
            if str(_row_value(row, "algorithm_version", 5)) != str(payload.get("algorithm_version")):
                raise ValueError("algorithm version mismatch")
            stored_counts = _row_value(row, "status_counts", 6)
            stored_counts_json = json.dumps(stored_counts, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
            expected_counts_json = json.dumps(
                payload.get("status_counts"),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            )
            if stored_counts_json != expected_counts_json:
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
        except PostgresProfessionalInvoicePaymentPersistenceError:
            raise
        except Exception as exc:
            raise PostgresProfessionalInvoicePaymentPersistenceError(
                "professional invoice/payment persisted evidence is invalid"
            ) from exc


__all__ = [
    "POSTGRES_PROFESSIONAL_INVOICE_PAYMENT_SCHEMA_SQL",
    "PostgresProfessionalInvoicePaymentPersistenceError",
    "PostgresProfessionalInvoicePaymentRepository",
]
