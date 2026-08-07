"""Tenant-RLS PostgreSQL persistence for non-posting acquisition PPA evidence."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any

from reconforge.domain.consolidation import ConsolidationError
from reconforge.domain.consolidation_ppa import (
    AcquisitionPurchasePriceAllocationRequest,
    AcquisitionPurchasePriceAllocationResult,
    prepare_acquisition_purchase_price_allocation,
    verify_acquisition_purchase_price_allocation_payload,
)
from reconforge.infrastructure.postgres import (
    set_local_tenant_scope,
    validate_legal_entity_id,
    validate_organization_id,
    validate_tenant_id,
)
from reconforge.infrastructure.postgres_domain import PostgresAuditEventRepository
from reconforge.platform.common import PlatformError, normalize_text

POSTGRES_CONSOLIDATION_PPA_SCHEMA_SQL = r"""
CREATE TABLE IF NOT EXISTS reconforge.consolidation_ppa_artifacts (
    tenant_id TEXT NOT NULL,
    id TEXT NOT NULL CHECK (id ~ '^ppa-[0-9a-f]{32}$'),
    acquisition_id TEXT NOT NULL,
    subsidiary_entity_code TEXT NOT NULL,
    period_id TEXT NOT NULL,
    reporting_currency TEXT NOT NULL CHECK (reporting_currency ~ '^[A-Z][A-Z0-9]{2,5}$'),
    request_digest TEXT NOT NULL CHECK (request_digest ~ '^[a-f0-9]{64}$'),
    result_digest TEXT NOT NULL CHECK (result_digest ~ '^[a-f0-9]{64}$'),
    request_payload JSONB NOT NULL CHECK (jsonb_typeof(request_payload) = 'object'),
    result_payload JSONB NOT NULL CHECK (
        jsonb_typeof(result_payload) = 'object' AND result_payload->>'posted' = 'false'
    ),
    prepared_by TEXT NOT NULL,
    approved_by TEXT NOT NULL,
    approved_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, result_digest),
    CONSTRAINT consolidation_ppa_actor_separation CHECK (prepared_by <> approved_by),
    FOREIGN KEY (tenant_id, prepared_by)
        REFERENCES reconforge.identity_users(tenant_id, id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id, approved_by)
        REFERENCES reconforge.identity_users(tenant_id, id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS consolidation_ppa_scope_idx
    ON reconforge.consolidation_ppa_artifacts
        (tenant_id, acquisition_id, period_id, created_at, id);
ALTER TABLE reconforge.consolidation_ppa_artifacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.consolidation_ppa_artifacts FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.consolidation_ppa_artifacts;
CREATE POLICY tenant_scope ON reconforge.consolidation_ppa_artifacts
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
CREATE OR REPLACE FUNCTION reconforge.guard_consolidation_ppa_artifact()
RETURNS TRIGGER LANGUAGE plpgsql AS $reconforge$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION 'consolidation PPA artifacts are immutable' USING ERRCODE='check_violation';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'consolidation PPA artifacts cannot be deleted' USING ERRCODE='check_violation';
    END IF;
    RETURN NEW;
END
$reconforge$;
DROP TRIGGER IF EXISTS consolidation_ppa_artifact_guard
    ON reconforge.consolidation_ppa_artifacts;
CREATE TRIGGER consolidation_ppa_artifact_guard
BEFORE UPDATE OR DELETE ON reconforge.consolidation_ppa_artifacts
FOR EACH ROW EXECUTE FUNCTION reconforge.guard_consolidation_ppa_artifact();
"""


class PostgresConsolidationPpaError(RuntimeError):
    """Safe PostgreSQL PPA persistence failure."""


def _row_value(row: Any, key: str, index: int) -> Any:
    return row.get(key) if isinstance(row, Mapping) else row[index]


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _payload(value: object, field: str) -> dict[str, object]:
    try:
        decoded = json.loads(value) if isinstance(value, str) else value
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise PostgresConsolidationPpaError(f"Persisted PPA {field} is invalid.") from exc
    if not isinstance(decoded, dict):
        raise PostgresConsolidationPpaError(f"Persisted PPA {field} is invalid.")
    return dict(decoded)


class PostgresConsolidationPpaRepository:
    """Persist verified PPA evidence without opening a posting path."""

    def __init__(
        self,
        connection: Any,
        tenant_id: str,
        organization_id: str | None = None,
        legal_entity_id: str | None = None,
    ) -> None:
        self.connection = connection
        self.tenant_id = validate_tenant_id(tenant_id)
        self.organization_id = validate_organization_id(organization_id)
        self.legal_entity_id = validate_legal_entity_id(legal_entity_id)
        if self.legal_entity_id is not None and self.organization_id is None:
            raise PlatformError("PPA legal-entity scope requires organization scope.")

    @staticmethod
    def _actor(value: str) -> str:
        actor = normalize_text(value, default="")
        if not actor:
            raise PlatformError("PPA actor is required.")
        return actor

    def _scope(self) -> None:
        set_local_tenant_scope(
            self.connection,
            self.tenant_id,
            self.organization_id,
            legal_entity_id=self.legal_entity_id,
        )

    def _scope_where(self) -> str:
        return (
            "tenant_id=%s AND organization_id IS NOT DISTINCT FROM %s "
            "AND legal_entity_id IS NOT DISTINCT FROM %s"
        )

    def _scope_params(self) -> tuple[str, str | None, str | None]:
        return self.tenant_id, self.organization_id, self.legal_entity_id

    def _artifact_id(self, request: AcquisitionPurchasePriceAllocationRequest) -> str:
        scope_prefix = f"{self.tenant_id}|{self.organization_id or ''}|{self.legal_entity_id or ''}"
        if self.organization_id is None and self.legal_entity_id is None:
            scope_prefix = self.tenant_id
        digest = hashlib.sha256(f"{scope_prefix}|{request.digest}".encode("ascii")).hexdigest()
        return f"ppa-{digest[:32]}"

    @staticmethod
    def _verify_result(
        request: AcquisitionPurchasePriceAllocationRequest,
        result: AcquisitionPurchasePriceAllocationResult,
    ) -> dict[str, object]:
        if not isinstance(request, AcquisitionPurchasePriceAllocationRequest):
            raise PostgresConsolidationPpaError("A typed PPA request is required.")
        if not isinstance(result, AcquisitionPurchasePriceAllocationResult):
            raise PostgresConsolidationPpaError("A typed PPA result is required.")
        try:
            expected = prepare_acquisition_purchase_price_allocation(request)
            payload = result.to_dict()
            verify_acquisition_purchase_price_allocation_payload(payload)
        except (ConsolidationError, TypeError, ValueError) as exc:
            raise PostgresConsolidationPpaError("PPA evidence failed deterministic verification.") from exc
        if result.request_digest != request.digest or result.result_digest != expected.result_digest:
            raise PostgresConsolidationPpaError("PPA request/result digest lineage is invalid.")
        if payload.get("posted") is not False:
            raise PostgresConsolidationPpaError("PostgreSQL PPA persistence cannot store posted artifacts.")
        return payload

    @classmethod
    def _decode_row(cls, row: Any) -> dict[str, Any]:
        result_payload = _payload(_row_value(row, "result_payload", 9), "result payload")
        try:
            verify_acquisition_purchase_price_allocation_payload(result_payload)
        except (ConsolidationError, TypeError, ValueError) as exc:
            raise PostgresConsolidationPpaError("Persisted PPA evidence failed replay verification.") from exc
        if result_payload.get("posted") is not False:
            raise PostgresConsolidationPpaError("Persisted PPA evidence is unexpectedly posted.")
        return {
            "id": str(_row_value(row, "id", 1)),
            "tenant_id": str(_row_value(row, "tenant_id", 0)),
            "acquisition_id": str(_row_value(row, "acquisition_id", 2)),
            "subsidiary_entity_code": str(_row_value(row, "subsidiary_entity_code", 3)),
            "period_id": str(_row_value(row, "period_id", 4)),
            "reporting_currency": str(_row_value(row, "reporting_currency", 5)),
            "request_digest": str(_row_value(row, "request_digest", 6)),
            "result_digest": str(_row_value(row, "result_digest", 7)),
            "request_payload": _payload(_row_value(row, "request_payload", 8), "request payload"),
            "result_payload": result_payload,
            "prepared_by": str(_row_value(row, "prepared_by", 10)),
            "approved_by": str(_row_value(row, "approved_by", 11)),
            "approved_at": str(_row_value(row, "approved_at", 12)),
            "created_at": str(_row_value(row, "created_at", 13)),
            "organization_id": _row_value(row, "organization_id", 14),
            "legal_entity_id": _row_value(row, "legal_entity_id", 15),
        }

    def persist(
        self,
        request: AcquisitionPurchasePriceAllocationRequest,
        result: AcquisitionPurchasePriceAllocationResult,
        *,
        artifact_id: str | None = None,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        actor = self._actor(actor_label)
        if actor != request.prepared_by:
            raise PlatformError("The authenticated PPA preparer must match the request preparer.")
        payload = self._verify_result(request, result)
        identifier = artifact_id or self._artifact_id(request)
        if not isinstance(identifier, str) or re.fullmatch(r"ppa-[0-9a-f]{32}", identifier) is None:
            raise PlatformError("PPA artifact ID is invalid.")
        try:
            with self.connection.transaction():
                self._scope()
                existing = self.connection.execute(
                    "SELECT * FROM reconforge.consolidation_ppa_artifacts WHERE "
                    + self._scope_where()
                    + " AND id=%s",
                    (*self._scope_params(), identifier),
                ).fetchone()
                if existing is not None:
                    stored = self._decode_row(existing)
                    if stored["request_digest"] != request.digest or stored["result_digest"] != result.result_digest:
                        raise PlatformError("PPA artifact identifier conflicts with immutable evidence.")
                    return stored
                self.connection.execute(
                    """INSERT INTO reconforge.consolidation_ppa_artifacts(
                         tenant_id,id,acquisition_id,subsidiary_entity_code,period_id,
                         reporting_currency,request_digest,result_digest,request_payload,
                         result_payload,prepared_by,approved_by,approved_at,
                         organization_id,legal_entity_id)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,CAST(%s AS jsonb),CAST(%s AS jsonb),%s,%s,%s,%s,%s)""",
                    (
                        self.tenant_id,
                        identifier,
                        request.acquisition_id,
                        request.subsidiary_entity_code,
                        request.period_id,
                        request.reporting_currency,
                        request.digest,
                        result.result_digest,
                        _json(request.to_dict()),
                        _json(payload),
                        request.prepared_by,
                        request.approved_by,
                        request.approved_at,
                        self.organization_id,
                        self.legal_entity_id,
                    ),
                )
                PostgresAuditEventRepository(self.connection, self.tenant_id).append(
                    actor_label=actor,
                    actor_user_id=actor,
                    object_type="consolidation_ppa_artifact",
                    object_id=identifier,
                    action="consolidation_ppa_artifact_created",
                    after_hash=result.result_digest,
                    metadata={
                        "acquisition_id": request.acquisition_id,
                        "period_id": request.period_id,
                        "posted": False,
                        "reporting_currency": request.reporting_currency,
                    },
                )
                return {
                    "id": identifier,
                    "tenant_id": self.tenant_id,
                    "organization_id": self.organization_id,
                    "legal_entity_id": self.legal_entity_id,
                    "acquisition_id": request.acquisition_id,
                    "period_id": request.period_id,
                    "request_digest": request.digest,
                    "result_digest": result.result_digest,
                    "posted": False,
                }
        except (PlatformError, PostgresConsolidationPpaError):
            raise
        except Exception as exc:
            raise PostgresConsolidationPpaError("PostgreSQL PPA persistence failed.") from exc

    def get(self, artifact_id: str, *, actor_label: str = "local-cli") -> dict[str, Any]:
        self._actor(actor_label)
        if not isinstance(artifact_id, str) or re.fullmatch(r"ppa-[0-9a-f]{32}", artifact_id) is None:
            raise PlatformError("PPA artifact ID is invalid.")
        try:
            with self.connection.transaction():
                self._scope()
                row = self.connection.execute(
                    "SELECT * FROM reconforge.consolidation_ppa_artifacts WHERE "
                    + self._scope_where()
                    + " AND id=%s",
                    (*self._scope_params(), artifact_id),
                ).fetchone()
                if row is None:
                    raise PostgresConsolidationPpaError("PPA artifact was not found.")
                return self._decode_row(row)
        except (PlatformError, PostgresConsolidationPpaError):
            raise
        except Exception as exc:
            raise PostgresConsolidationPpaError("PostgreSQL PPA read failed.") from exc


__all__ = ["POSTGRES_CONSOLIDATION_PPA_SCHEMA_SQL", "PostgresConsolidationPpaError", "PostgresConsolidationPpaRepository"]
