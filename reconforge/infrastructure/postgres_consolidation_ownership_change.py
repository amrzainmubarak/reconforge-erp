"""Tenant-RLS PostgreSQL persistence for non-posting ownership-change evidence."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

from reconforge.domain.consolidation import ConsolidationError
from reconforge.domain.consolidation_ownership_changes import (
    OwnershipChangeAdjustmentRequest,
    OwnershipChangeAdjustmentResult,
    prepare_ownership_change_adjustment,
    verify_ownership_change_adjustment_payload,
)
from reconforge.infrastructure.postgres import set_local_tenant_scope, validate_tenant_id
from reconforge.infrastructure.postgres_domain import PostgresAuditEventRepository
from reconforge.platform.common import PlatformError, normalize_text
from reconforge.utils.money import Money

POSTGRES_CONSOLIDATION_OWNERSHIP_CHANGE_SCHEMA_SQL = r"""
CREATE TABLE IF NOT EXISTS reconforge.consolidation_ownership_change_artifacts (
    tenant_id TEXT NOT NULL,
    id TEXT NOT NULL CHECK (id ~ '^ownchg-[0-9a-f]{32}$'),
    change_id TEXT NOT NULL,
    subsidiary_entity_code TEXT NOT NULL,
    period_id TEXT NOT NULL,
    effective_date DATE NOT NULL,
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
    CONSTRAINT consolidation_ownership_change_actor_separation CHECK (prepared_by <> approved_by),
    FOREIGN KEY (tenant_id, prepared_by)
        REFERENCES reconforge.identity_users(tenant_id, id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id, approved_by)
        REFERENCES reconforge.identity_users(tenant_id, id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS consolidation_ownership_change_scope_idx
    ON reconforge.consolidation_ownership_change_artifacts
        (tenant_id, subsidiary_entity_code, period_id, effective_date, created_at, id);
ALTER TABLE reconforge.consolidation_ownership_change_artifacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.consolidation_ownership_change_artifacts FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.consolidation_ownership_change_artifacts;
CREATE POLICY tenant_scope ON reconforge.consolidation_ownership_change_artifacts
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
CREATE OR REPLACE FUNCTION reconforge.guard_consolidation_ownership_change_artifact()
RETURNS TRIGGER LANGUAGE plpgsql AS $reconforge$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION 'consolidation ownership-change artifacts are immutable' USING ERRCODE='check_violation';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'consolidation ownership-change artifacts cannot be deleted' USING ERRCODE='check_violation';
    END IF;
    RETURN NEW;
END
$reconforge$;
DROP TRIGGER IF EXISTS consolidation_ownership_change_artifact_guard
    ON reconforge.consolidation_ownership_change_artifacts;
CREATE TRIGGER consolidation_ownership_change_artifact_guard
BEFORE UPDATE OR DELETE ON reconforge.consolidation_ownership_change_artifacts
FOR EACH ROW EXECUTE FUNCTION reconforge.guard_consolidation_ownership_change_artifact();
"""


class PostgresConsolidationOwnershipChangeError(RuntimeError):
    """Safe PostgreSQL ownership-change persistence failure."""


def _row_value(row: Any, key: str, index: int) -> Any:
    return row.get(key) if isinstance(row, Mapping) else row[index]


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _json_digest(value: object) -> str:
    return hashlib.sha256(_json(value).encode("ascii")).hexdigest()


def _payload(value: object, field: str) -> dict[str, object]:
    try:
        decoded = json.loads(value) if isinstance(value, str) else value
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise PostgresConsolidationOwnershipChangeError(
            f"Persisted ownership-change {field} is invalid."
        ) from exc
    if not isinstance(decoded, dict):
        raise PostgresConsolidationOwnershipChangeError(f"Persisted ownership-change {field} is invalid.")
    return dict(decoded)


def _money(payload: Mapping[str, object], field: str) -> Money:
    value = payload.get(field)
    if not isinstance(value, Mapping):
        raise ConsolidationError(f"Ownership-change {field} is invalid.")
    return Money.from_canonical_dict(value)


def _request_from_payload(payload: Mapping[str, object]) -> OwnershipChangeAdjustmentRequest:
    try:
        return OwnershipChangeAdjustmentRequest(
            change_id=str(payload["change_id"]),
            subsidiary_entity_code=str(payload["subsidiary_entity_code"]),
            period_id=str(payload["period_id"]),
            effective_date=str(payload["effective_date"]),
            reporting_currency=str(payload["reporting_currency"]),
            prior_group_ownership_percentage=Decimal(str(payload["prior_group_ownership_percentage"])),
            new_group_ownership_percentage=Decimal(str(payload["new_group_ownership_percentage"])),
            net_assets=_money(payload, "net_assets"),
            consideration_effect=_money(payload, "consideration_effect"),
            nci_account_code=str(payload["nci_account_code"]),
            consideration_account_code=str(payload["consideration_account_code"]),
            parent_equity_account_code=str(payload["parent_equity_account_code"]),
            policy_id=str(payload["policy_id"]),
            policy_version=str(payload["policy_version"]),
            source_reference=str(payload["source_reference"]),
            source_digest=str(payload["source_digest"]),
            prepared_by=str(payload["prepared_by"]),
            prepared_at=str(payload["prepared_at"]),
            approved_by=str(payload["approved_by"]),
            approved_at=str(payload["approved_at"]),
        )
    except (ConsolidationError, InvalidOperation, KeyError, TypeError, ValueError) as exc:
        raise PostgresConsolidationOwnershipChangeError(
            "Persisted ownership-change request failed replay verification."
        ) from exc


class PostgresConsolidationOwnershipChangeRepository:
    """Persist verified ownership-change evidence without opening a posting path."""

    def __init__(self, connection: Any, tenant_id: str) -> None:
        self.connection = connection
        self.tenant_id = validate_tenant_id(tenant_id)

    @staticmethod
    def _actor(value: str) -> str:
        actor = normalize_text(value, default="")
        if not actor:
            raise PlatformError("Ownership-change actor is required.")
        return actor

    def _scope(self) -> None:
        set_local_tenant_scope(self.connection, self.tenant_id)

    def _artifact_id(self, request: OwnershipChangeAdjustmentRequest) -> str:
        digest = hashlib.sha256(f"{self.tenant_id}|{request.digest}".encode("ascii")).hexdigest()
        return f"ownchg-{digest[:32]}"

    @staticmethod
    def _verify_result(
        request: OwnershipChangeAdjustmentRequest,
        result: OwnershipChangeAdjustmentResult,
    ) -> dict[str, object]:
        if not isinstance(request, OwnershipChangeAdjustmentRequest):
            raise PostgresConsolidationOwnershipChangeError("A typed ownership-change request is required.")
        if not isinstance(result, OwnershipChangeAdjustmentResult):
            raise PostgresConsolidationOwnershipChangeError("A typed ownership-change result is required.")
        try:
            expected = prepare_ownership_change_adjustment(request)
            payload = result.to_dict()
            verify_ownership_change_adjustment_payload(payload)
        except (ConsolidationError, InvalidOperation, TypeError, ValueError) as exc:
            raise PostgresConsolidationOwnershipChangeError(
                "Ownership-change evidence failed deterministic verification."
            ) from exc
        if result.request_digest != request.digest or result.result_digest != expected.result_digest:
            raise PostgresConsolidationOwnershipChangeError(
                "Ownership-change request/result digest lineage is invalid."
            )
        if payload.get("posted") is not False:
            raise PostgresConsolidationOwnershipChangeError(
                "PostgreSQL ownership-change persistence cannot store posted artifacts."
            )
        return payload

    @classmethod
    def _decode_row(cls, row: Any) -> dict[str, Any]:
        request_payload = _payload(_row_value(row, "request_payload", 9), "request payload")
        request = _request_from_payload(request_payload)
        request_digest = str(_row_value(row, "request_digest", 7))
        if request.digest != request_digest or _json_digest(request_payload) != request_digest:
            raise PostgresConsolidationOwnershipChangeError("Persisted ownership-change request digest mismatch.")
        result_payload = _payload(_row_value(row, "result_payload", 10), "result payload")
        try:
            verify_ownership_change_adjustment_payload(result_payload)
            expected = prepare_ownership_change_adjustment(request)
        except (ConsolidationError, InvalidOperation, TypeError, ValueError) as exc:
            raise PostgresConsolidationOwnershipChangeError(
                "Persisted ownership-change evidence failed replay verification."
            ) from exc
        result_digest = str(_row_value(row, "result_digest", 8))
        if (
            result_payload.get("posted") is not False
            or result_payload.get("request_digest") != request_digest
            or result_payload.get("result_digest") != result_digest
            or expected.result_digest != result_digest
        ):
            raise PostgresConsolidationOwnershipChangeError(
                "Persisted ownership-change result digest mismatch."
            )
        return {
            "id": str(_row_value(row, "id", 1)),
            "tenant_id": str(_row_value(row, "tenant_id", 0)),
            "change_id": str(_row_value(row, "change_id", 2)),
            "subsidiary_entity_code": str(_row_value(row, "subsidiary_entity_code", 3)),
            "period_id": str(_row_value(row, "period_id", 4)),
            "effective_date": str(_row_value(row, "effective_date", 5)),
            "reporting_currency": str(_row_value(row, "reporting_currency", 6)),
            "request_digest": request_digest,
            "result_digest": result_digest,
            "request_payload": request_payload,
            "result_payload": result_payload,
            "prepared_by": str(_row_value(row, "prepared_by", 11)),
            "approved_by": str(_row_value(row, "approved_by", 12)),
            "approved_at": str(_row_value(row, "approved_at", 13)),
            "created_at": str(_row_value(row, "created_at", 14)),
        }

    def persist(
        self,
        request: OwnershipChangeAdjustmentRequest,
        result: OwnershipChangeAdjustmentResult,
        *,
        artifact_id: str | None = None,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        actor = self._actor(actor_label)
        if actor != request.prepared_by:
            raise PlatformError("The authenticated ownership-change preparer must match the request preparer.")
        payload = self._verify_result(request, result)
        identifier = artifact_id or self._artifact_id(request)
        if not isinstance(identifier, str) or re.fullmatch(r"ownchg-[0-9a-f]{32}", identifier) is None:
            raise PlatformError("Ownership-change artifact ID is invalid.")
        try:
            with self.connection.transaction():
                self._scope()
                existing = self.connection.execute(
                    "SELECT * FROM reconforge.consolidation_ownership_change_artifacts "
                    "WHERE tenant_id=%s AND id=%s",
                    (self.tenant_id, identifier),
                ).fetchone()
                if existing is not None:
                    stored = self._decode_row(existing)
                    if stored["request_digest"] != request.digest or stored["result_digest"] != result.result_digest:
                        raise PlatformError("Ownership-change artifact identifier conflicts with immutable evidence.")
                    return stored
                duplicate = self.connection.execute(
                    "SELECT * FROM reconforge.consolidation_ownership_change_artifacts "
                    "WHERE tenant_id=%s AND result_digest=%s",
                    (self.tenant_id, result.result_digest),
                ).fetchone()
                if duplicate is not None:
                    stored = self._decode_row(duplicate)
                    if stored["request_digest"] != request.digest:
                        raise PlatformError("Ownership-change result digest conflicts with immutable evidence.")
                    return stored
                self.connection.execute(
                    """INSERT INTO reconforge.consolidation_ownership_change_artifacts(
                         tenant_id,id,change_id,subsidiary_entity_code,period_id,effective_date,
                         reporting_currency,request_digest,result_digest,request_payload,result_payload,
                         prepared_by,approved_by,approved_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,CAST(%s AS jsonb),CAST(%s AS jsonb),%s,%s,%s)""",
                    (
                        self.tenant_id,
                        identifier,
                        request.change_id,
                        request.subsidiary_entity_code,
                        request.period_id,
                        request.effective_date,
                        request.reporting_currency,
                        request.digest,
                        result.result_digest,
                        _json(request.to_dict()),
                        _json(payload),
                        request.prepared_by,
                        request.approved_by,
                        request.approved_at,
                    ),
                )
                PostgresAuditEventRepository(self.connection, self.tenant_id).append(
                    actor_label=actor,
                    actor_user_id=actor,
                    object_type="consolidation_ownership_change_artifact",
                    object_id=identifier,
                    action="consolidation_ownership_change_artifact_created",
                    after_hash=result.result_digest,
                    metadata={
                        "change_id": request.change_id,
                        "subsidiary_entity_code": request.subsidiary_entity_code,
                        "period_id": request.period_id,
                        "posted": False,
                        "reporting_currency": request.reporting_currency,
                    },
                )
                return {
                    "id": identifier,
                    "tenant_id": self.tenant_id,
                    "change_id": request.change_id,
                    "subsidiary_entity_code": request.subsidiary_entity_code,
                    "period_id": request.period_id,
                    "request_digest": request.digest,
                    "result_digest": result.result_digest,
                    "posted": False,
                }
        except (PlatformError, PostgresConsolidationOwnershipChangeError):
            raise
        except Exception as exc:
            raise PostgresConsolidationOwnershipChangeError(
                "PostgreSQL ownership-change persistence failed."
            ) from exc

    def get(self, artifact_id: str, *, actor_label: str = "local-cli") -> dict[str, Any]:
        self._actor(actor_label)
        if not isinstance(artifact_id, str) or re.fullmatch(r"ownchg-[0-9a-f]{32}", artifact_id) is None:
            raise PlatformError("Ownership-change artifact ID is invalid.")
        try:
            with self.connection.transaction():
                self._scope()
                row = self.connection.execute(
                    "SELECT * FROM reconforge.consolidation_ownership_change_artifacts "
                    "WHERE tenant_id=%s AND id=%s",
                    (self.tenant_id, artifact_id),
                ).fetchone()
                if row is None:
                    raise PostgresConsolidationOwnershipChangeError(
                        "Ownership-change artifact was not found."
                    )
                return self._decode_row(row)
        except (PlatformError, PostgresConsolidationOwnershipChangeError):
            raise
        except Exception as exc:
            raise PostgresConsolidationOwnershipChangeError(
                "PostgreSQL ownership-change read failed."
            ) from exc


__all__ = [
    "POSTGRES_CONSOLIDATION_OWNERSHIP_CHANGE_SCHEMA_SQL",
    "PostgresConsolidationOwnershipChangeError",
    "PostgresConsolidationOwnershipChangeRepository",
]
