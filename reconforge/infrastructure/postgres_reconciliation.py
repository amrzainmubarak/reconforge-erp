"""Tenant-scoped persistence for deterministic reconciliation runs.

The local matching engine remains responsible for candidate generation and
global assignment.  This boundary persists its canonical input manifest,
results, and exceptions under PostgreSQL while enforcing the financial
invariants that make a completed run explainable and reproducible.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, cast

from reconforge.infrastructure.postgres import PostgresConfigurationError, normalize_scope_id, validate_tenant_id
from reconforge.io.persisted import (
    PersistedJsonError,
    decode_postgres_reconciliation_attributes,
    decode_postgres_reconciliation_evidence,
    decode_postgres_reconciliation_lineage,
    decode_postgres_reconciliation_rule,
    encode_audit_metadata,
    encode_postgres_outbox_payload,
    encode_postgres_reconciliation_attributes,
    encode_postgres_reconciliation_evidence,
    encode_postgres_reconciliation_lineage,
    encode_postgres_reconciliation_rule,
)
from reconforge.utils.time import utc_now_text

_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_DECIMAL_PATTERN = re.compile(r"^-?(0|[0-9]+)(\.[0-9]+)?$")
_CURRENCY_PATTERN = re.compile(r"^[A-Z]{3}$")
_RUN_STATUSES = ("Running", "Complete", "Failed")
_EXECUTION_STATUSES = ("Queued", "Running", "Complete", "Failed", "Cancelled")
_SIDES = ("Left", "Right")
_RESULT_STATUSES = ("Matched", "Unmatched", "Invalid", "Ambiguous", "Duplicate", "Rejected")
_EXCEPTION_SEVERITIES = ("Low", "Medium", "High", "Critical")
_EXCEPTION_STATUSES = ("Open", "Assigned", "Resolved", "Accepted Risk", "Closed")
_RUN_SELECT = (
    "tenant_id, id, name, left_source, right_source, status, algorithm_version, "
    "rule_json, input_hash, idempotency_key, created_by, created_at, completed_at, "
    "left_input_count, right_input_count, result_count, matched_count, exception_count, "
    "input_manifest_hash, result_set_hash, execution_status, execution_worker_id, "
    "execution_claimed_at, execution_lease_until, execution_progress, execution_attempt, "
    "execution_started_at, execution_finished_at, execution_error, cancel_requested"
)
_RUN_SELECT_PREFIX = "SELECT " + _RUN_SELECT
_RUN_CREATE_QUERY = """
INSERT INTO reconforge.reconciliation_runs
    (tenant_id, id, name, left_source, right_source, algorithm_version, rule_json,
    input_hash, idempotency_key, created_by)
VALUES (%s, %s, %s, %s, %s, %s, CAST(%s AS jsonb), %s, %s, %s)
RETURNING tenant_id, id, name, left_source, right_source, status, algorithm_version, rule_json,
    input_hash, idempotency_key, created_by, created_at, completed_at,
    left_input_count, right_input_count, result_count, matched_count, exception_count,
    input_manifest_hash, result_set_hash, execution_status, execution_worker_id,
    execution_claimed_at, execution_lease_until, execution_progress, execution_attempt,
    execution_started_at, execution_finished_at, execution_error, cancel_requested
"""
_RUN_CLAIM_QUERY = """
UPDATE reconforge.reconciliation_runs
SET execution_status = 'Running', execution_worker_id = %s,
    execution_claimed_at = now(),
    execution_lease_until = now() + (%s * INTERVAL '1 second'),
    execution_attempt = execution_attempt + 1,
    execution_started_at = COALESCE(execution_started_at, now()),
    execution_finished_at = NULL, execution_error = ''
WHERE tenant_id = %s AND id = %s AND status = 'Running'
  AND cancel_requested = FALSE
  AND (execution_status = 'Queued' OR (execution_status = 'Running' AND execution_lease_until <= now()))
RETURNING tenant_id, id, name, left_source, right_source, status, algorithm_version, rule_json,
    input_hash, idempotency_key, created_by, created_at, completed_at,
    left_input_count, right_input_count, result_count, matched_count, exception_count,
    input_manifest_hash, result_set_hash, execution_status, execution_worker_id,
    execution_claimed_at, execution_lease_until, execution_progress, execution_attempt,
    execution_started_at, execution_finished_at, execution_error, cancel_requested
"""
_RUN_HEARTBEAT_QUERY = """
UPDATE reconforge.reconciliation_runs
SET execution_progress = %s,
    execution_claimed_at = now(),
    execution_lease_until = now() + (%s * INTERVAL '1 second')
WHERE tenant_id = %s AND id = %s AND status = 'Running'
  AND execution_status = 'Running' AND execution_worker_id = %s
RETURNING tenant_id, id, name, left_source, right_source, status, algorithm_version, rule_json,
    input_hash, idempotency_key, created_by, created_at, completed_at,
    left_input_count, right_input_count, result_count, matched_count, exception_count,
    input_manifest_hash, result_set_hash, execution_status, execution_worker_id,
    execution_claimed_at, execution_lease_until, execution_progress, execution_attempt,
    execution_started_at, execution_finished_at, execution_error, cancel_requested
"""
_RUN_CANCEL_QUEUED_QUERY = """
UPDATE reconforge.reconciliation_runs
SET execution_status = 'Cancelled', execution_finished_at = now(),
    execution_progress = 0, cancel_requested = TRUE
WHERE tenant_id = %s AND id = %s AND status = 'Running' AND execution_status = 'Queued'
RETURNING tenant_id, id, name, left_source, right_source, status, algorithm_version, rule_json,
    input_hash, idempotency_key, created_by, created_at, completed_at,
    left_input_count, right_input_count, result_count, matched_count, exception_count,
    input_manifest_hash, result_set_hash, execution_status, execution_worker_id,
    execution_claimed_at, execution_lease_until, execution_progress, execution_attempt,
    execution_started_at, execution_finished_at, execution_error, cancel_requested
"""
_RUN_REQUEST_CANCEL_QUERY = """
UPDATE reconforge.reconciliation_runs
SET cancel_requested = TRUE
WHERE tenant_id = %s AND id = %s AND status = 'Running'
RETURNING tenant_id, id, name, left_source, right_source, status, algorithm_version, rule_json,
    input_hash, idempotency_key, created_by, created_at, completed_at,
    left_input_count, right_input_count, result_count, matched_count, exception_count,
    input_manifest_hash, result_set_hash, execution_status, execution_worker_id,
    execution_claimed_at, execution_lease_until, execution_progress, execution_attempt,
    execution_started_at, execution_finished_at, execution_error, cancel_requested
"""
_RUN_MARK_CANCELLED_QUERY = """
UPDATE reconforge.reconciliation_runs
SET execution_status = 'Cancelled', execution_finished_at = now(),
    execution_worker_id = NULL, execution_claimed_at = NULL,
    execution_lease_until = NULL, execution_progress = LEAST(execution_progress, 99)
WHERE tenant_id = %s AND id = %s AND status = 'Running'
  AND execution_status = 'Running' AND execution_worker_id = %s
RETURNING tenant_id, id, name, left_source, right_source, status, algorithm_version, rule_json,
    input_hash, idempotency_key, created_by, created_at, completed_at,
    left_input_count, right_input_count, result_count, matched_count, exception_count,
    input_manifest_hash, result_set_hash, execution_status, execution_worker_id,
    execution_claimed_at, execution_lease_until, execution_progress, execution_attempt,
    execution_started_at, execution_finished_at, execution_error, cancel_requested
"""
_RUN_FAIL_QUERY = """
UPDATE reconforge.reconciliation_runs
SET execution_status = 'Failed', execution_finished_at = now(),
    execution_worker_id = NULL, execution_claimed_at = NULL,
    execution_lease_until = NULL, execution_error = %s
WHERE tenant_id = %s AND id = %s AND status = 'Running'
  AND execution_status = 'Running' AND execution_worker_id = %s
RETURNING tenant_id, id, name, left_source, right_source, status, algorithm_version, rule_json,
    input_hash, idempotency_key, created_by, created_at, completed_at,
    left_input_count, right_input_count, result_count, matched_count, exception_count,
    input_manifest_hash, result_set_hash, execution_status, execution_worker_id,
    execution_claimed_at, execution_lease_until, execution_progress, execution_attempt,
    execution_started_at, execution_finished_at, execution_error, cancel_requested
"""
_RUN_REQUEUE_QUERY = """
UPDATE reconforge.reconciliation_runs
SET execution_status = 'Queued', execution_worker_id = NULL,
    execution_claimed_at = NULL, execution_lease_until = NULL,
    execution_progress = 0, execution_finished_at = NULL,
    execution_error = '', cancel_requested = FALSE
WHERE tenant_id = %s AND id = %s AND status = 'Running'
RETURNING tenant_id, id, name, left_source, right_source, status, algorithm_version, rule_json,
    input_hash, idempotency_key, created_by, created_at, completed_at,
    left_input_count, right_input_count, result_count, matched_count, exception_count,
    input_manifest_hash, result_set_hash, execution_status, execution_worker_id,
    execution_claimed_at, execution_lease_until, execution_progress, execution_attempt,
    execution_started_at, execution_finished_at, execution_error, cancel_requested
"""
_RUN_COMPLETE_QUERY = """
UPDATE reconforge.reconciliation_runs
SET status = 'Complete', completed_at = now(), left_input_count = %s,
    right_input_count = %s, result_count = %s, matched_count = %s,
    exception_count = %s, input_manifest_hash = %s, result_set_hash = %s,
    execution_status = 'Complete', execution_progress = 100,
    execution_finished_at = now(), execution_worker_id = NULL,
    execution_claimed_at = NULL, execution_lease_until = NULL,
    execution_error = '', cancel_requested = FALSE
WHERE tenant_id = %s AND id = %s AND status = 'Running'
RETURNING tenant_id, id, name, left_source, right_source, status, algorithm_version, rule_json,
    input_hash, idempotency_key, created_by, created_at, completed_at,
    left_input_count, right_input_count, result_count, matched_count, exception_count,
    input_manifest_hash, result_set_hash, execution_status, execution_worker_id,
    execution_claimed_at, execution_lease_until, execution_progress, execution_attempt,
    execution_started_at, execution_finished_at, execution_error, cancel_requested
"""
_RUN_COMPLETE_WITH_WORKER_QUERY = """
UPDATE reconforge.reconciliation_runs
SET status = 'Complete', completed_at = now(), left_input_count = %s,
    right_input_count = %s, result_count = %s, matched_count = %s,
    exception_count = %s, input_manifest_hash = %s, result_set_hash = %s,
    execution_status = 'Complete', execution_progress = 100,
    execution_finished_at = now(), execution_worker_id = NULL,
    execution_claimed_at = NULL, execution_lease_until = NULL,
    execution_error = '', cancel_requested = FALSE
WHERE tenant_id = %s AND id = %s AND status = 'Running'
  AND execution_worker_id = %s
RETURNING tenant_id, id, name, left_source, right_source, status, algorithm_version, rule_json,
    input_hash, idempotency_key, created_by, created_at, completed_at,
    left_input_count, right_input_count, result_count, matched_count, exception_count,
    input_manifest_hash, result_set_hash, execution_status, execution_worker_id,
    execution_claimed_at, execution_lease_until, execution_progress, execution_attempt,
    execution_started_at, execution_finished_at, execution_error, cancel_requested
"""


class PostgresReconciliationValidationError(ValueError):
    """Raised when a reconciliation input violates the canonical contract."""


class PostgresReconciliationIntegrityError(RuntimeError):
    """Raised when a run or result would violate an immutable invariant."""


class PostgresReconciliationBusyError(PostgresReconciliationIntegrityError):
    """Raised when another worker currently owns a run lease."""


class PostgresReconciliationNotFoundError(PostgresReconciliationIntegrityError):
    """Raised when a tenant-scoped run or child record does not exist."""


@dataclass(frozen=True)
class PostgresReconciliationRepository:
    """Persist and validate reconciliation runs without committing."""

    connection: Any

    _RUN_COLUMNS = (
        "tenant_id",
        "id",
        "name",
        "left_source",
        "right_source",
        "status",
        "algorithm_version",
        "rule_json",
        "input_hash",
        "idempotency_key",
        "created_by",
        "created_at",
        "completed_at",
        "left_input_count",
        "right_input_count",
        "result_count",
        "matched_count",
        "exception_count",
        "input_manifest_hash",
        "result_set_hash",
        "execution_status",
        "execution_worker_id",
        "execution_claimed_at",
        "execution_lease_until",
        "execution_progress",
        "execution_attempt",
        "execution_started_at",
        "execution_finished_at",
        "execution_error",
        "cancel_requested",
    )
    _INPUT_COLUMNS = (
        "tenant_id",
        "run_id",
        "side",
        "source_id",
        "record_hash",
        "amount_decimal",
        "amount_original",
        "currency_code",
        "date_original",
        "date_value",
        "reference_original",
        "reference_normalized",
        "attributes_json",
        "valid",
        "allowed_uses",
        "created_at",
    )
    _RESULT_COLUMNS = (
        "tenant_id",
        "id",
        "run_id",
        "left_id",
        "right_id",
        "match_type",
        "confidence",
        "explanation",
        "amount_difference",
        "date_difference_days",
        "status",
        "reason_code",
        "lineage_json",
        "created_at",
    )
    _EXCEPTION_COLUMNS = (
        "tenant_id",
        "id",
        "run_id",
        "exception_type",
        "source_side",
        "source_id",
        "title",
        "explanation",
        "severity",
        "risk_score",
        "workflow_status",
        "owner_id",
        "reason_code",
        "evidence_json",
        "created_at",
        "updated_at",
    )
    _CHECKPOINT_COLUMNS = (
        "tenant_id",
        "run_id",
        "partition_key",
        "status",
        "input_count",
        "result_count",
        "exception_count",
        "output_hash",
        "worker_id",
        "created_at",
        "completed_at",
    )

    @staticmethod
    def _tenant(value: object) -> str:
        try:
            return validate_tenant_id(str(value))
        except PostgresConfigurationError as exc:
            raise PostgresReconciliationValidationError(str(exc)) from exc

    @staticmethod
    def _id(value: object, field_name: str) -> str:
        try:
            normalized = normalize_scope_id(str(value), field_name=field_name)
        except PostgresConfigurationError as exc:
            raise PostgresReconciliationValidationError(str(exc)) from exc
        if not _ID_PATTERN.fullmatch(normalized):
            raise PostgresReconciliationValidationError(f"{field_name} has an invalid identifier.")
        return normalized

    @staticmethod
    def _text(value: object, field_name: str, *, maximum: int = 255, allow_blank: bool = False) -> str:
        normalized = str(value or "").strip()
        if not normalized and not allow_blank:
            raise PostgresReconciliationValidationError(f"{field_name} must not be blank.")
        if len(normalized) > maximum:
            raise PostgresReconciliationValidationError(f"{field_name} must be at most {maximum} characters.")
        if any(ord(character) < 32 or ord(character) == 127 for character in normalized):
            raise PostgresReconciliationValidationError(f"{field_name} must contain printable characters only.")
        return " ".join(normalized.split())

    @classmethod
    def _choice(cls, value: object, field_name: str, choices: tuple[str, ...]) -> str:
        normalized = cls._text(value, field_name, maximum=64).casefold()
        for choice in choices:
            if choice.casefold() == normalized:
                return choice
        raise PostgresReconciliationValidationError(f"{field_name} must be one of: {', '.join(choices)}.")

    @classmethod
    def _decimal(
        cls,
        value: object,
        field_name: str,
        *,
        allow_negative: bool = False,
        allow_blank: bool = False,
        maximum_scale: int = 18,
        maximum_integer_digits: int = 20,
    ) -> str | None:
        if value is None or (allow_blank and not str(value).strip()):
            return None
        if isinstance(value, (bool, float)):
            raise PostgresReconciliationValidationError(f"{field_name} must be an exact decimal, not a binary float.")
        raw = str(value).strip()
        if not _DECIMAL_PATTERN.fullmatch(raw) or (not allow_negative and raw.startswith("-")):
            raise PostgresReconciliationValidationError(f"{field_name} must be an exact decimal.")
        try:
            parsed = Decimal(raw)
        except InvalidOperation as exc:
            raise PostgresReconciliationValidationError(f"{field_name} must be an exact decimal.") from exc
        if not parsed.is_finite():
            raise PostgresReconciliationValidationError(f"{field_name} must be finite.")
        digits = parsed.as_tuple().digits
        exponent = parsed.as_tuple().exponent
        if not isinstance(exponent, int):
            raise PostgresReconciliationValidationError(f"{field_name} must be a finite decimal.")
        scale = max(0, -exponent)
        integer_digits = max(1, len(digits) + exponent) if exponent >= 0 else max(1, len(digits) - scale)
        if scale > maximum_scale or integer_digits > maximum_integer_digits:
            raise PostgresReconciliationValidationError(f"{field_name} exceeds the supported decimal precision.")
        canonical = format(parsed, "f")
        if "." in canonical:
            canonical = canonical.rstrip("0").rstrip(".")
        return canonical or "0"

    @classmethod
    def _currency(cls, value: object) -> str:
        normalized = cls._text(value, "currency_code", maximum=3, allow_blank=True).upper()
        if normalized and not _CURRENCY_PATTERN.fullmatch(normalized):
            raise PostgresReconciliationValidationError("currency_code must be a three-letter ISO-style code.")
        return normalized

    @classmethod
    def _date(cls, value: object) -> str | None:
        if value is None or not str(value).strip():
            return None
        raw = cls._text(value, "date_value", maximum=10)
        try:
            parsed = datetime.strptime(raw, "%Y-%m-%d").date()
        except ValueError as exc:
            raise PostgresReconciliationValidationError("date_value must use YYYY-MM-DD format.") from exc
        return parsed.isoformat()

    @classmethod
    def _json_text(cls, value: Mapping[str, object] | None, field_name: str) -> str:
        encoders = {
            "rule": encode_postgres_reconciliation_rule,
            "attributes": encode_postgres_reconciliation_attributes,
            "lineage": encode_postgres_reconciliation_lineage,
            "evidence": encode_postgres_reconciliation_evidence,
        }
        try:
            return encoders[field_name](value).text
        except (KeyError, PersistedJsonError) as exc:
            raise PostgresReconciliationValidationError(f"{field_name} must be a bounded JSON object.") from exc

    @classmethod
    def _canonical_json_text(cls, value: object, field_name: str) -> str:
        """Canonicalize a JSONB value returned by either tuple or dict cursors."""

        decoders = {
            "rule": decode_postgres_reconciliation_rule,
            "attributes": decode_postgres_reconciliation_attributes,
            "lineage": decode_postgres_reconciliation_lineage,
            "evidence": decode_postgres_reconciliation_evidence,
        }
        try:
            return decoders[field_name](value).text
        except (KeyError, PersistedJsonError) as exc:
            raise PostgresReconciliationIntegrityError(f"Stored {field_name} is invalid.") from exc

    @staticmethod
    def _audit_metadata_text(value: Mapping[str, object] | None) -> str:
        try:
            return encode_audit_metadata(value).text
        except PersistedJsonError as exc:
            raise PostgresReconciliationValidationError("metadata must be JSON-serializable.") from exc

    @staticmethod
    def _outbox_payload_text(value: Mapping[str, object]) -> str:
        try:
            return encode_postgres_outbox_payload(value).text
        except PersistedJsonError as exc:
            raise PostgresReconciliationValidationError("outbox payload must be JSON-serializable.") from exc

    @staticmethod
    def _row_value(row: Any, key: str, index: int) -> Any:
        if isinstance(row, Mapping):
            return row.get(key)
        return row[index]

    @classmethod
    def _record(cls, row: Any, columns: tuple[str, ...]) -> dict[str, Any]:
        if row is None:
            raise PostgresReconciliationIntegrityError("PostgreSQL reconciliation operation returned no record.")
        if isinstance(row, Mapping):
            record = {str(key): value for key, value in row.items()}
        else:
            values = tuple(row)
            if len(values) != len(columns):
                raise PostgresReconciliationIntegrityError("PostgreSQL reconciliation record shape was unexpected.")
            record = dict(zip(columns, values, strict=True))
        json_fields = {
            "rule_json": "rule",
            "attributes_json": "attributes",
            "lineage_json": "lineage",
            "evidence_json": "evidence",
        }
        for key, field_name in json_fields.items():
            if key in record:
                canonical = cls._canonical_json_text(record[key], field_name)
                decoder = {
                    "rule": decode_postgres_reconciliation_rule,
                    "attributes": decode_postgres_reconciliation_attributes,
                    "lineage": decode_postgres_reconciliation_lineage,
                    "evidence": decode_postgres_reconciliation_evidence,
                }[field_name]
                record[key] = decoder(canonical).payload
        return record

    @staticmethod
    def _hash_payload(payload: object) -> str:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def _run_row(self, tenant: str, run_id: str, *, lock: bool = False) -> dict[str, Any]:
        query = _RUN_SELECT_PREFIX + " FROM reconforge.reconciliation_runs WHERE tenant_id = %s AND id = %s"
        if lock:
            query += " FOR UPDATE"
        row = self.connection.execute(query, (tenant, run_id)).fetchone()
        if row is None:
            raise PostgresReconciliationNotFoundError("Reconciliation run was not found.")
        return self._record(row, self._RUN_COLUMNS)

    @classmethod
    def _page(cls, limit: int | None, offset: int) -> tuple[int | None, int]:
        if limit is not None and (isinstance(limit, bool) or limit < 1 or limit > 1_000):
            raise PostgresReconciliationValidationError("limit must be between 1 and 1000.")
        if isinstance(offset, bool) or offset < 0 or offset > 10_000_000:
            raise PostgresReconciliationValidationError("offset must be between 0 and 10000000.")
        return limit, offset

    def list_runs(
        self,
        *,
        tenant_id: str,
        status: str = "",
        execution_status: str = "",
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List this tenant's run metadata in a stable page order."""

        tenant = self._tenant(tenant_id)
        page_limit, page_offset = self._page(limit, offset)
        normalized_status = "" if not str(status).strip() else self._choice(status, "status", _RUN_STATUSES)
        execution_filter = str(execution_status or "").strip().casefold()
        valid_execution_filters = {"", "active", *(value.casefold() for value in _EXECUTION_STATUSES)}
        if execution_filter not in valid_execution_filters:
            raise PostgresReconciliationValidationError(
                "execution_status must be queued, running, complete, failed, cancelled, active, or blank."
            )
        query = _RUN_SELECT_PREFIX + " FROM reconforge.reconciliation_runs WHERE tenant_id = %s"
        parameters: list[object] = [tenant]
        if normalized_status:
            query += " AND status = %s"
            parameters.append(normalized_status)
        if execution_filter == "active":
            query += " AND execution_status IN ('Queued', 'Running')"
        elif execution_filter:
            query += " AND execution_status = %s"
            parameters.append(next(value for value in _EXECUTION_STATUSES if value.casefold() == execution_filter))
        query += " ORDER BY created_at DESC, id DESC LIMIT %s OFFSET %s"
        parameters.extend((page_limit, page_offset))
        cursor = self.connection.execute(query, tuple(parameters))
        return [self._record(row, self._RUN_COLUMNS) for row in cursor.fetchall()]

    def _append_audit_outbox(
        self,
        *,
        tenant: str,
        action: str,
        resource_id: str,
        before_state_hash: str,
        after_state_hash: str,
        actor_id: str,
        request_id: str,
        reason: str,
        metadata: Mapping[str, object] | None,
        payload: Mapping[str, object],
    ) -> None:
        actor = self._text(actor_id, "actor_id", maximum=160)
        request = self._text(request_id, "request_id", maximum=160, allow_blank=True)
        audit_reason = self._text(reason, "reason", maximum=500, allow_blank=True)
        metadata_json = self._audit_metadata_text(metadata)
        outbox_payload_json = self._outbox_payload_text(payload)
        self.connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (tenant,))
        event_id = self._hash_payload({"tenant_id": tenant, "action": action, "resource_id": resource_id, "after": after_state_hash})
        previous = self.connection.execute(
            "SELECT event_hash FROM reconforge.audit_events WHERE tenant_id = %s ORDER BY event_sequence DESC LIMIT 1",
            (tenant,),
        ).fetchone()
        previous_hash = "" if previous is None else str(self._row_value(previous, "event_hash", 0) or "")
        occurred_at = utc_now_text()
        event_hash = self._hash_payload(
            {
                "tenant_id": tenant,
                "event_id": event_id,
                "actor_id": actor,
                "action": action,
                "resource_type": "reconciliation_run",
                "resource_id": resource_id,
                "occurred_at": occurred_at,
                "request_id": request,
                "before_state_hash": before_state_hash,
                "after_state_hash": after_state_hash,
                "previous_event_hash": previous_hash,
                "reason": audit_reason,
                "metadata": metadata_json,
            }
        )
        self.connection.execute(
            """
            INSERT INTO reconforge.audit_events
                (tenant_id, event_id, actor_id, action, resource_type, resource_id, occurred_at,
                 request_id, before_state_hash, after_state_hash, previous_event_hash, event_hash,
                 reason, metadata)
            VALUES (%s, %s, %s, %s, 'reconciliation_run', %s, %s, %s, %s, %s, %s, %s, %s, CAST(%s AS jsonb))
            ON CONFLICT (tenant_id, event_id) DO NOTHING
            """,
            (tenant, event_id, actor, action, resource_id, occurred_at, request, before_state_hash, after_state_hash, previous_hash, event_hash, audit_reason, metadata_json),
        )
        outbox_id = self._hash_payload({"tenant_id": tenant, "event_type": f"reconciliation.{action}", "resource_id": resource_id})
        self.connection.execute(
            """
            INSERT INTO reconforge.outbox_events
                (tenant_id, event_id, event_type, aggregate_type, aggregate_id, payload)
            VALUES (%s, %s, %s, 'reconciliation_run', %s, CAST(%s AS jsonb))
            ON CONFLICT (tenant_id, event_id) DO NOTHING
            """,
            (tenant, outbox_id, f"reconciliation.{action}", resource_id, outbox_payload_json),
        )

    def create_run(
        self,
        *,
        tenant_id: str,
        run_id: str,
        name: str,
        left_source: str,
        right_source: str,
        algorithm_version: str,
        rule: Mapping[str, object],
        input_hash: str,
        actor_id: str,
        idempotency_key: str | None = None,
        request_id: str = "",
        reason: str = "",
    ) -> dict[str, Any]:
        """Create one Running run with a stable fingerprint."""

        tenant = self._tenant(tenant_id)
        identifier = self._id(run_id, "run_id")
        run_name = self._text(name, "name", maximum=255)
        left = self._text(left_source, "left_source", maximum=512)
        right = self._text(right_source, "right_source", maximum=512)
        algorithm = self._text(algorithm_version, "algorithm_version", maximum=64)
        rules = self._json_text(rule, "rule")
        source_hash = self._text(input_hash, "input_hash", maximum=128)
        idem = None if idempotency_key is None or not str(idempotency_key).strip() else self._text(idempotency_key, "idempotency_key", maximum=160)
        if idem is None:
            existing = self.connection.execute(
                _RUN_SELECT_PREFIX
                + " FROM reconforge.reconciliation_runs "
                "WHERE tenant_id = %s AND id = %s FOR UPDATE",
                (tenant, identifier),
            ).fetchone()
        else:
            existing = self.connection.execute(
                _RUN_SELECT_PREFIX
                + " FROM reconforge.reconciliation_runs "
                "WHERE tenant_id = %s AND (id = %s OR idempotency_key = %s) FOR UPDATE",
                (tenant, identifier, idem),
            ).fetchone()
        if existing is not None:
            record = self._record(existing, self._RUN_COLUMNS)
            fingerprint = self._hash_payload({"name": run_name, "left_source": left, "right_source": right, "algorithm_version": algorithm, "rule": rules, "input_hash": source_hash})
            existing_fingerprint = self._hash_payload(
                {
                    "name": record["name"],
                    "left_source": record["left_source"],
                    "right_source": record["right_source"],
                    "algorithm_version": record["algorithm_version"],
                    "rule": self._canonical_json_text(record["rule_json"], "rule"),
                    "input_hash": record["input_hash"],
                }
            )
            if (idem is None and str(record["id"]) != identifier) or fingerprint != existing_fingerprint:
                raise PostgresReconciliationIntegrityError("Run identifier or idempotency key already refers to different content.")
            return self.get_run(tenant_id=tenant, run_id=str(record["id"]))
        cursor = self.connection.execute(
            _RUN_CREATE_QUERY,
            (tenant, identifier, run_name, left, right, algorithm, rules, source_hash, idem, self._text(actor_id, "actor_id", maximum=160)),
        )
        record = self._record(cursor.fetchone(), self._RUN_COLUMNS)
        after_hash = self._hash_payload(record)
        self._append_audit_outbox(
            tenant=tenant,
            action="run_created",
            resource_id=identifier,
            before_state_hash="",
            after_state_hash=after_hash,
            actor_id=actor_id,
            request_id=request_id,
            reason=reason,
            metadata={"algorithm_version": algorithm},
            payload={"run_id": identifier, "status": "Running", "after_state_hash": after_hash},
        )
        return self.get_run(tenant_id=tenant, run_id=identifier)

    @staticmethod
    def _lease_seconds(value: int) -> int:
        if isinstance(value, bool) or not 1 <= int(value) <= 86_400:
            raise PostgresReconciliationValidationError("lease_seconds is outside the supported range.")
        return int(value)

    @staticmethod
    def _progress(value: int) -> int:
        if isinstance(value, bool) or not 0 <= int(value) <= 100:
            raise PostgresReconciliationValidationError("progress must be between 0 and 100.")
        return int(value)

    def claim_run(
        self,
        *,
        tenant_id: str,
        run_id: str,
        worker_id: str,
        lease_seconds: int = 300,
    ) -> dict[str, Any]:
        """Claim a queued or expired run for one worker without committing."""

        tenant = self._tenant(tenant_id)
        run = self._id(run_id, "run_id")
        worker = self._text(worker_id, "worker_id", maximum=160)
        lease = self._lease_seconds(lease_seconds)
        before = self._run_row(tenant, run, lock=True)
        if str(before["status"]) != "Running":
            raise PostgresReconciliationIntegrityError("Only a Running reconciliation can be claimed.")
        if str(before.get("execution_status") or "Queued") in {"Complete", "Failed", "Cancelled"}:
            raise PostgresReconciliationIntegrityError("Reconciliation execution must be requeued before it can run.")
        if bool(before.get("cancel_requested", False)):
            raise PostgresReconciliationBusyError("Reconciliation execution has a pending cancellation request.")
        cursor = self.connection.execute(
            _RUN_CLAIM_QUERY,
            (worker, lease, tenant, run),
        )
        claimed_row = cursor.fetchone()
        if claimed_row is None:
            raise PostgresReconciliationBusyError("Reconciliation run is already leased by another worker.")
        claimed = self._record(claimed_row, self._RUN_COLUMNS)
        self._append_audit_outbox(
            tenant=tenant,
            action="run_claimed",
            resource_id=run,
            before_state_hash=self._hash_payload(before),
            after_state_hash=self._hash_payload(claimed),
            actor_id=worker,
            request_id="",
            reason="",
            metadata={"worker_id": worker, "execution_attempt": claimed.get("execution_attempt", 0)},
            payload={"run_id": run, "worker_id": worker, "execution_attempt": claimed.get("execution_attempt", 0)},
        )
        return claimed

    def heartbeat_run(
        self,
        *,
        tenant_id: str,
        run_id: str,
        worker_id: str,
        progress: int,
        lease_seconds: int = 300,
    ) -> dict[str, Any]:
        """Extend a worker lease and publish bounded progress metadata."""

        tenant = self._tenant(tenant_id)
        run = self._id(run_id, "run_id")
        worker = self._text(worker_id, "worker_id", maximum=160)
        selected_progress = self._progress(progress)
        lease = self._lease_seconds(lease_seconds)
        cursor = self.connection.execute(
            _RUN_HEARTBEAT_QUERY,
            (selected_progress, lease, tenant, run, worker),
        )
        row = cursor.fetchone()
        if row is None:
            raise PostgresReconciliationIntegrityError("Reconciliation execution is not leased by this worker.")
        return self._record(row, self._RUN_COLUMNS)

    def cancel_run(
        self,
        *,
        tenant_id: str,
        run_id: str,
        actor_id: str,
        request_id: str = "",
        reason: str = "",
    ) -> dict[str, Any]:
        """Request cooperative cancellation without deleting financial records."""

        tenant = self._tenant(tenant_id)
        run = self._id(run_id, "run_id")
        before = self._run_row(tenant, run, lock=True)
        execution_status = str(before.get("execution_status") or "Queued")
        if execution_status in {"Complete", "Cancelled"}:
            raise PostgresReconciliationIntegrityError("Reconciliation execution is already terminal.")
        if execution_status == "Queued":
            cursor = self.connection.execute(
                _RUN_CANCEL_QUEUED_QUERY,
                (tenant, run),
            )
            cancelled = self._record(cursor.fetchone(), self._RUN_COLUMNS)
            after_hash = self._hash_payload(cancelled)
            self._append_audit_outbox(
                tenant=tenant,
                action="run_cancelled",
                resource_id=run,
                before_state_hash=self._hash_payload(before),
                after_state_hash=after_hash,
                actor_id=actor_id,
                request_id=request_id,
                reason=reason,
                metadata={"execution_status": execution_status},
                payload={"run_id": run, "execution_status": "Cancelled", "after_state_hash": after_hash},
            )
            return cancelled
        if bool(before.get("cancel_requested", False)):
            return before
        cursor = self.connection.execute(
            _RUN_REQUEST_CANCEL_QUERY,
            (tenant, run),
        )
        cancelled = self._record(cursor.fetchone(), self._RUN_COLUMNS)
        after_hash = self._hash_payload(cancelled)
        self._append_audit_outbox(
            tenant=tenant,
            action="run_cancel_requested",
            resource_id=run,
            before_state_hash=self._hash_payload(before),
            after_state_hash=after_hash,
            actor_id=actor_id,
            request_id=request_id,
            reason=reason,
            metadata={"execution_status": execution_status},
            payload={"run_id": run, "cancel_requested": True, "after_state_hash": after_hash},
        )
        return cancelled

    def mark_cancelled(
        self,
        *,
        tenant_id: str,
        run_id: str,
        worker_id: str,
        actor_id: str,
        request_id: str = "",
        reason: str = "",
    ) -> dict[str, Any]:
        """Finalize a cooperative cancellation owned by the current worker."""

        tenant = self._tenant(tenant_id)
        run = self._id(run_id, "run_id")
        worker = self._text(worker_id, "worker_id", maximum=160)
        before = self._run_row(tenant, run, lock=True)
        cursor = self.connection.execute(
            _RUN_MARK_CANCELLED_QUERY,
            (tenant, run, worker),
        )
        cancelled = self._record(cursor.fetchone(), self._RUN_COLUMNS)
        after_hash = self._hash_payload(cancelled)
        self._append_audit_outbox(
            tenant=tenant,
            action="run_cancelled",
            resource_id=run,
            before_state_hash=self._hash_payload(before),
            after_state_hash=after_hash,
            actor_id=actor_id,
            request_id=request_id,
            reason=reason,
            metadata={"worker_id": worker},
            payload={"run_id": run, "execution_status": "Cancelled", "after_state_hash": after_hash},
        )
        return cancelled

    def fail_run(
        self,
        *,
        tenant_id: str,
        run_id: str,
        worker_id: str,
        actor_id: str,
        error: str,
        request_id: str = "",
        reason: str = "",
    ) -> dict[str, Any]:
        """Record a safe retryable execution failure for the owning worker."""

        tenant = self._tenant(tenant_id)
        run = self._id(run_id, "run_id")
        worker = self._text(worker_id, "worker_id", maximum=160)
        safe_error = (str(error).strip() or "reconciliation execution failed")[:4_000]
        before = self._run_row(tenant, run, lock=True)
        cursor = self.connection.execute(
            _RUN_FAIL_QUERY,
            (safe_error, tenant, run, worker),
        )
        failed = self._record(cursor.fetchone(), self._RUN_COLUMNS)
        after_hash = self._hash_payload(failed)
        self._append_audit_outbox(
            tenant=tenant,
            action="run_failed",
            resource_id=run,
            before_state_hash=self._hash_payload(before),
            after_state_hash=after_hash,
            actor_id=actor_id,
            request_id=request_id,
            reason=reason,
            metadata={"worker_id": worker, "error": safe_error},
            payload={"run_id": run, "execution_status": "Failed", "error": safe_error, "after_state_hash": after_hash},
        )
        return failed

    def requeue_run(
        self,
        *,
        tenant_id: str,
        run_id: str,
        actor_id: str,
        request_id: str = "",
        reason: str = "",
    ) -> dict[str, Any]:
        """Explicitly make a failed or cancelled run eligible for retry."""

        tenant = self._tenant(tenant_id)
        run = self._id(run_id, "run_id")
        before = self._run_row(tenant, run, lock=True)
        if str(before.get("execution_status") or "Queued") not in {"Failed", "Cancelled"}:
            raise PostgresReconciliationIntegrityError("Only failed or cancelled executions can be requeued.")
        cursor = self.connection.execute(
            _RUN_REQUEUE_QUERY,
            (tenant, run),
        )
        requeued = self._record(cursor.fetchone(), self._RUN_COLUMNS)
        after_hash = self._hash_payload(requeued)
        self._append_audit_outbox(
            tenant=tenant,
            action="run_requeued",
            resource_id=run,
            before_state_hash=self._hash_payload(before),
            after_state_hash=after_hash,
            actor_id=actor_id,
            request_id=request_id,
            reason=reason,
            metadata={},
            payload={"run_id": run, "execution_status": "Queued", "after_state_hash": after_hash},
        )
        return requeued

    def register_input(
        self,
        *,
        tenant_id: str,
        run_id: str,
        side: str,
        source_id: str,
        record_hash: str,
        amount: object | None = None,
        amount_original: str = "",
        currency_code: str = "",
        date_original: str = "",
        date_value: object | None = None,
        reference_original: str = "",
        reference_normalized: str = "",
        attributes: Mapping[str, object] | None = None,
        valid: bool = True,
        allowed_uses: int = 1,
    ) -> dict[str, Any]:
        """Register one canonical source record before results are appended."""

        tenant = self._tenant(tenant_id)
        run = self._id(run_id, "run_id")
        selected_side = self._choice(side, "side", _SIDES)
        source = self._text(source_id, "source_id", maximum=255)
        fingerprint = self._text(record_hash, "record_hash", maximum=128)
        amount_decimal = self._decimal(amount, "amount", allow_negative=True, allow_blank=True)
        original_amount = self._text(amount_original, "amount_original", maximum=255, allow_blank=True)
        currency = self._currency(currency_code)
        original_date = self._text(date_original, "date_original", maximum=64, allow_blank=True)
        parsed_date = self._date(date_value)
        original_reference = self._text(reference_original, "reference_original", maximum=512, allow_blank=True)
        normalized_reference = self._text(reference_normalized, "reference_normalized", maximum=512, allow_blank=True)
        attributes_json = self._json_text(attributes, "attributes")
        if not 1 <= int(allowed_uses) <= 1_000:
            raise PostgresReconciliationValidationError("allowed_uses must be between 1 and 1000.")
        self._run_row(tenant, run, lock=True)
        cursor = self.connection.execute(
            """
            INSERT INTO reconforge.reconciliation_inputs
                (tenant_id, run_id, side, source_id, record_hash, amount_decimal, amount_original,
                 currency_code, date_original, date_value, reference_original, reference_normalized,
                 attributes_json, valid, allowed_uses)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CAST(%s AS jsonb), %s, %s)
            ON CONFLICT (tenant_id, run_id, side, source_id) DO NOTHING
            RETURNING tenant_id, run_id, side, source_id, record_hash, amount_decimal, amount_original,
                      currency_code, date_original, date_value, reference_original, reference_normalized,
                      attributes_json,
                      valid, allowed_uses, created_at
            """,
            (tenant, run, selected_side, source, fingerprint, amount_decimal, original_amount, currency, original_date, parsed_date, original_reference, normalized_reference, attributes_json, bool(valid), int(allowed_uses)),
        )
        row = cursor.fetchone()
        if row is None:
            row = self.connection.execute(
                """
                SELECT tenant_id, run_id, side, source_id, record_hash, amount_decimal, amount_original,
                       currency_code, date_original, date_value, reference_original, reference_normalized,
                       attributes_json,
                       valid, allowed_uses, created_at
                FROM reconforge.reconciliation_inputs
                WHERE tenant_id = %s AND run_id = %s AND side = %s AND source_id = %s
                """,
                (tenant, run, selected_side, source),
            ).fetchone()
            existing = self._record(row, self._INPUT_COLUMNS)
            expected = {"record_hash": fingerprint, "amount_decimal": amount_decimal, "allowed_uses": int(allowed_uses)}
            if any(str(existing[key]) != str(value) for key, value in expected.items()):
                raise PostgresReconciliationIntegrityError("Input source identifier already refers to different content.")
            return existing
        return self._record(row, self._INPUT_COLUMNS)

    def append_result(
        self,
        *,
        tenant_id: str,
        run_id: str,
        left_id: str = "",
        right_id: str = "",
        match_type: str,
        confidence: object,
        explanation: str,
        amount_difference: object = "0",
        date_difference_days: int | None = None,
        status: str,
        reason_code: str = "",
        lineage: Mapping[str, object] | None = None,
    ) -> dict[str, Any]:
        """Append one deterministic match/unmatched/invalid result."""

        tenant = self._tenant(tenant_id)
        run = self._id(run_id, "run_id")
        left = self._text(left_id, "left_id", maximum=255, allow_blank=True)
        right = self._text(right_id, "right_id", maximum=255, allow_blank=True)
        if not left and not right:
            raise PostgresReconciliationValidationError("A result must identify a left or right source record.")
        selected_type = self._text(match_type, "match_type", maximum=64)
        confidence_text = self._decimal(confidence, "confidence", maximum_scale=8, maximum_integer_digits=1)
        if confidence_text is None or Decimal(confidence_text) > Decimal("1"):
            raise PostgresReconciliationValidationError("confidence must be between 0 and 1.")
        explanation_text = self._text(explanation, "explanation", maximum=4_000)
        difference = self._decimal(amount_difference, "amount_difference") or "0"
        if date_difference_days is None:
            day_difference = None
        else:
            try:
                day_difference = int(date_difference_days)
            except (TypeError, ValueError) as exc:
                raise PostgresReconciliationValidationError("date_difference_days must be an integer.") from exc
            if not 0 <= day_difference <= 10_000_000:
                raise PostgresReconciliationValidationError("date_difference_days is outside the supported range.")
        selected_status = self._choice(status, "status", _RESULT_STATUSES)
        reason = self._text(reason_code, "reason_code", maximum=64, allow_blank=True)
        lineage_json = self._json_text(lineage, "lineage")
        self._run_row(tenant, run, lock=True)
        references = self.connection.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM reconforge.reconciliation_inputs
                  WHERE tenant_id = %s AND run_id = %s AND side = 'Left' AND source_id = %s) AS left_exists,
                (SELECT COUNT(*) FROM reconforge.reconciliation_inputs
                  WHERE tenant_id = %s AND run_id = %s AND side = 'Right' AND source_id = %s) AS right_exists
            """,
            (tenant, run, left, tenant, run, right),
        ).fetchone()
        if left and int(self._row_value(references, "left_exists", 0) or 0) != 1:
            raise PostgresReconciliationIntegrityError("Result references an unregistered left input record.")
        if right and int(self._row_value(references, "right_exists", 1) or 0) != 1:
            raise PostgresReconciliationIntegrityError("Result references an unregistered right input record.")
        result_id = "result-" + self._hash_payload({"tenant_id": tenant, "run_id": run, "left_id": left, "right_id": right, "match_type": selected_type, "status": selected_status})[:48]
        cursor = self.connection.execute(
            """
            INSERT INTO reconforge.reconciliation_results
                (tenant_id, id, run_id, left_id, right_id, match_type, confidence, explanation,
                 amount_difference, date_difference_days, status, reason_code, lineage_json)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CAST(%s AS jsonb))
            ON CONFLICT (tenant_id, id) DO NOTHING
            RETURNING tenant_id, id, run_id, left_id, right_id, match_type, confidence, explanation,
                      amount_difference, date_difference_days, status, reason_code, lineage_json, created_at
            """,
            (tenant, result_id, run, left, right, selected_type, confidence_text, explanation_text, difference, day_difference, selected_status, reason, lineage_json),
        )
        row = cursor.fetchone()
        if row is None:
            row = self.connection.execute(
                """
                SELECT tenant_id, id, run_id, left_id, right_id, match_type, confidence, explanation,
                       amount_difference, date_difference_days, status, reason_code, lineage_json, created_at
                FROM reconforge.reconciliation_results
                WHERE tenant_id = %s AND id = %s
                """,
                (tenant, result_id),
            ).fetchone()
        return self._record(row, self._RESULT_COLUMNS)

    def append_exception(
        self,
        *,
        tenant_id: str,
        run_id: str,
        exception_type: str,
        source_side: str,
        source_id: str,
        title: str,
        explanation: str,
        severity: str,
        risk_score: object,
        reason_code: str,
        owner_id: str = "",
        evidence: Mapping[str, object] | None = None,
    ) -> dict[str, Any]:
        """Persist one explainable exception under a Running reconciliation."""

        tenant = self._tenant(tenant_id)
        run = self._id(run_id, "run_id")
        selected_type = self._text(exception_type, "exception_type", maximum=64)
        side = self._choice(source_side, "source_side", _SIDES)
        source = self._text(source_id, "source_id", maximum=255)
        selected_title = self._text(title, "title", maximum=255)
        details = self._text(explanation, "explanation", maximum=4_000)
        selected_severity = self._choice(severity, "severity", _EXCEPTION_SEVERITIES)
        score = self._decimal(risk_score, "risk_score", maximum_scale=8, maximum_integer_digits=1)
        if score is None or Decimal(score) > Decimal("1"):
            raise PostgresReconciliationValidationError("risk_score must be between 0 and 1.")
        reason = self._text(reason_code, "reason_code", maximum=64)
        owner = self._text(owner_id, "owner_id", maximum=160, allow_blank=True)
        evidence_json = self._json_text(evidence, "evidence")
        self._run_row(tenant, run, lock=True)
        exception_id = "exception-" + self._hash_payload({"tenant_id": tenant, "run_id": run, "exception_type": selected_type, "source_side": side, "source_id": source, "reason_code": reason})[:48]
        cursor = self.connection.execute(
            """
            INSERT INTO reconforge.reconciliation_exceptions
                (tenant_id, id, run_id, exception_type, source_side, source_id, title, explanation,
                 severity, risk_score, owner_id, reason_code, evidence_json)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CAST(%s AS jsonb))
            ON CONFLICT (tenant_id, id) DO NOTHING
            RETURNING tenant_id, id, run_id, exception_type, source_side, source_id, title, explanation,
                      severity, risk_score, workflow_status, owner_id, reason_code, evidence_json,
                      created_at, updated_at
            """,
            (tenant, exception_id, run, selected_type, side, source, selected_title, details, selected_severity, score, owner, reason, evidence_json),
        )
        return self._record(cursor.fetchone(), self._EXCEPTION_COLUMNS)

    def list_checkpoints(self, *, tenant_id: str, run_id: str) -> list[dict[str, Any]]:
        """List completed partition checkpoints in deterministic key order."""

        tenant = self._tenant(tenant_id)
        run = self._id(run_id, "run_id")
        self._run_row(tenant, run)
        cursor = self.connection.execute(
            """
            SELECT tenant_id, run_id, partition_key, status, input_count,
                   result_count, exception_count, output_hash, worker_id,
                   created_at, completed_at
            FROM reconforge.reconciliation_execution_checkpoints
            WHERE tenant_id = %s AND run_id = %s AND status = 'Complete'
            ORDER BY partition_key
            """,
            (tenant, run),
        )
        return [self._record(row, self._CHECKPOINT_COLUMNS) for row in cursor.fetchall()]

    def append_partition(
        self,
        *,
        tenant_id: str,
        run_id: str,
        partition_key: str,
        input_count: int,
        results: Sequence[Mapping[str, object]] = (),
        exceptions: Sequence[Mapping[str, object]] = (),
        worker_id: str,
        request_id: str = "",
        reason: str = "",
    ) -> dict[str, Any]:
        """Persist one partition's output and completion marker atomically.

        A checkpoint is the idempotency boundary for resumable execution.  A
        retry with the same partition key returns the existing marker without
        inserting duplicate financial output; a retry with different output is
        rejected as an integrity violation.
        """

        tenant = self._tenant(tenant_id)
        run = self._id(run_id, "run_id")
        partition = self._text(partition_key, "partition_key", maximum=128)
        worker = self._text(worker_id, "worker_id", maximum=160)
        if isinstance(input_count, bool) or not 0 <= int(input_count) <= 100_000_000:
            raise PostgresReconciliationValidationError("input_count must be between 0 and 100000000.")
        result_fields = {
            "left_id",
            "right_id",
            "match_type",
            "confidence",
            "explanation",
            "amount_difference",
            "date_difference_days",
            "status",
            "reason_code",
            "lineage",
        }
        exception_fields = {
            "exception_type",
            "source_side",
            "source_id",
            "title",
            "explanation",
            "severity",
            "risk_score",
            "reason_code",
            "owner_id",
            "evidence",
        }
        result_values = [cast(dict[str, Any], dict(record)) for record in results]
        exception_values = [cast(dict[str, Any], dict(record)) for record in exceptions]
        for values in result_values:
            unknown = set(values).difference(result_fields)
            if unknown:
                raise PostgresReconciliationValidationError(
                    f"Partition result contains unsupported fields: {', '.join(sorted(unknown))}."
                )
            self._json_text(cast(Mapping[str, object] | None, values.get("lineage")), "lineage")
        for values in exception_values:
            unknown = set(values).difference(exception_fields)
            if unknown:
                raise PostgresReconciliationValidationError(
                    f"Partition exception contains unsupported fields: {', '.join(sorted(unknown))}."
                )
            self._json_text(cast(Mapping[str, object] | None, values.get("evidence")), "evidence")
        output_payload = {
            "partition_key": partition,
            "results": result_values,
            "exceptions": exception_values,
        }
        output_hash = self._hash_payload(output_payload)
        before = self._run_row(tenant, run, lock=True)
        if str(before.get("status")) != "Running" or str(before.get("execution_status") or "Queued") not in {"Queued", "Running"}:
            raise PostgresReconciliationIntegrityError("Only an active reconciliation can receive a partition checkpoint.")
        if str(before.get("execution_worker_id") or "") != worker:
            raise PostgresReconciliationIntegrityError("Reconciliation execution is not leased by this worker.")
        existing_row = self.connection.execute(
            """
            SELECT tenant_id, run_id, partition_key, status, input_count,
                   result_count, exception_count, output_hash, worker_id,
                   created_at, completed_at
            FROM reconforge.reconciliation_execution_checkpoints
            WHERE tenant_id = %s AND run_id = %s AND partition_key = %s
            FOR UPDATE
            """,
            (tenant, run, partition),
        ).fetchone()
        if existing_row is not None:
            existing = self._record(existing_row, self._CHECKPOINT_COLUMNS)
            if (
                str(existing.get("output_hash")) != output_hash
                or int(existing.get("input_count") or 0) != int(input_count)
                or int(existing.get("result_count") or 0) != len(results)
                or int(existing.get("exception_count") or 0) != len(exceptions)
            ):
                raise PostgresReconciliationIntegrityError("Partition checkpoint already contains different output.")
            return existing
        for values in result_values:
            self.append_result(tenant_id=tenant, run_id=run, **values)
        for values in exception_values:
            self.append_exception(tenant_id=tenant, run_id=run, **values)
        cursor = self.connection.execute(
            """
            INSERT INTO reconforge.reconciliation_execution_checkpoints
                (tenant_id, run_id, partition_key, status, input_count,
                 result_count, exception_count, output_hash, worker_id)
            VALUES (%s, %s, %s, 'Complete', %s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id, run_id, partition_key) DO NOTHING
            RETURNING tenant_id, run_id, partition_key, status, input_count,
                      result_count, exception_count, output_hash, worker_id,
                      created_at, completed_at
            """,
            (tenant, run, partition, int(input_count), len(results), len(exceptions), output_hash, worker),
        )
        row = cursor.fetchone()
        if row is None:
            row = self.connection.execute(
                """
                SELECT tenant_id, run_id, partition_key, status, input_count,
                       result_count, exception_count, output_hash, worker_id,
                       created_at, completed_at
                FROM reconforge.reconciliation_execution_checkpoints
                WHERE tenant_id = %s AND run_id = %s AND partition_key = %s
                """,
                (tenant, run, partition),
            ).fetchone()
        checkpoint = self._record(row, self._CHECKPOINT_COLUMNS)
        if str(checkpoint.get("output_hash")) != output_hash:
            raise PostgresReconciliationIntegrityError("Partition checkpoint changed while it was being persisted.")
        after_hash = self._hash_payload(checkpoint)
        self._append_audit_outbox(
            tenant=tenant,
            action="partition_checkpointed",
            resource_id=f"{run}:{partition}",
            before_state_hash=self._hash_payload(before),
            after_state_hash=after_hash,
            actor_id=worker,
            request_id=request_id,
            reason=reason,
            metadata={
                "run_id": run,
                "partition_key": partition,
                "input_count": int(input_count),
                "result_count": len(results),
                "exception_count": len(exceptions),
            },
            payload={"run_id": run, "partition_key": partition, "output_hash": output_hash},
        )
        return checkpoint

    def complete_run(
        self,
        *,
        tenant_id: str,
        run_id: str,
        actor_id: str,
        worker_id: str = "",
        request_id: str = "",
        reason: str = "",
    ) -> dict[str, Any]:
        """Complete a run only when all registered inputs are represented."""

        tenant = self._tenant(tenant_id)
        run = self._id(run_id, "run_id")
        before = self._run_row(tenant, run, lock=True)
        if str(before["status"]) != "Running":
            raise PostgresReconciliationIntegrityError("Only a Running reconciliation can be completed.")
        execution_status = str(before.get("execution_status") or "Queued")
        if execution_status not in {"Queued", "Running"}:
            raise PostgresReconciliationIntegrityError("Only a queued or running reconciliation can be completed.")
        worker = str(worker_id or "").strip()
        if worker and str(before.get("execution_worker_id") or "") != worker:
            raise PostgresReconciliationIntegrityError("Reconciliation execution is not leased by this worker.")
        if bool(before.get("cancel_requested", False)):
            raise PostgresReconciliationIntegrityError("Reconciliation execution has a pending cancellation request.")
        counts = self.connection.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM reconforge.reconciliation_inputs WHERE tenant_id = %s AND run_id = %s AND side = 'Left') AS left_count,
                (SELECT COUNT(*) FROM reconforge.reconciliation_inputs WHERE tenant_id = %s AND run_id = %s AND side = 'Right') AS right_count,
                (SELECT COUNT(*) FROM reconforge.reconciliation_results WHERE tenant_id = %s AND run_id = %s) AS result_count,
                (SELECT COUNT(*) FROM reconforge.reconciliation_results WHERE tenant_id = %s AND run_id = %s AND status = 'Matched') AS matched_count,
                (SELECT COUNT(*) FROM reconforge.reconciliation_exceptions WHERE tenant_id = %s AND run_id = %s) AS exception_count
            """,
            (tenant, run, tenant, run, tenant, run, tenant, run, tenant, run),
        ).fetchone()
        left_count = int(self._row_value(counts, "left_count", 0) or 0)
        right_count = int(self._row_value(counts, "right_count", 1) or 0)
        result_count = int(self._row_value(counts, "result_count", 2) or 0)
        matched_count = int(self._row_value(counts, "matched_count", 3) or 0)
        exception_count = int(self._row_value(counts, "exception_count", 4) or 0)
        missing = self.connection.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM reconforge.reconciliation_inputs inputs
                  WHERE inputs.tenant_id = %s AND inputs.run_id = %s AND inputs.side = 'Left'
                    AND NOT EXISTS (SELECT 1 FROM reconforge.reconciliation_results results WHERE results.tenant_id = inputs.tenant_id AND results.run_id = inputs.run_id AND results.left_id = inputs.source_id)) AS missing_left,
                (SELECT COUNT(*) FROM reconforge.reconciliation_inputs inputs
                  WHERE inputs.tenant_id = %s AND inputs.run_id = %s AND inputs.side = 'Right'
                    AND NOT EXISTS (SELECT 1 FROM reconforge.reconciliation_results results WHERE results.tenant_id = inputs.tenant_id AND results.run_id = inputs.run_id AND results.right_id = inputs.source_id)) AS missing_right
            """,
            (tenant, run, tenant, run),
        ).fetchone()
        missing_left = int(self._row_value(missing, "missing_left", 0) or 0)
        missing_right = int(self._row_value(missing, "missing_right", 1) or 0)
        if missing_left or missing_right:
            raise PostgresReconciliationIntegrityError(
                f"Reconciliation cannot complete: {missing_left} left and {missing_right} right inputs have no result."
            )
        overused = self.connection.execute(
            """
            SELECT COUNT(*) FROM (
                SELECT inputs.side, inputs.source_id
                FROM reconforge.reconciliation_inputs inputs
                JOIN reconforge.reconciliation_results results
                  ON results.tenant_id = inputs.tenant_id AND results.run_id = inputs.run_id
                 AND ((inputs.side = 'Left' AND results.left_id = inputs.source_id)
                   OR (inputs.side = 'Right' AND results.right_id = inputs.source_id))
                WHERE inputs.tenant_id = %s AND inputs.run_id = %s
                GROUP BY inputs.side, inputs.source_id, inputs.allowed_uses
                HAVING COUNT(*) > MAX(inputs.allowed_uses)
            ) violations
            """,
            (tenant, run),
        ).fetchone()
        if int(self._row_value(overused, "count", 0) or 0) > 0:
            raise PostgresReconciliationIntegrityError("Reconciliation cannot complete: an input record exceeded its allowed use count.")
        inputs = self.list_inputs(tenant_id=tenant, run_id=run)
        results = self.list_results(tenant_id=tenant, run_id=run)
        input_manifest_hash = self._hash_payload(inputs)
        result_set_hash = self._hash_payload(results)
        completion_parameters: tuple[object, ...] = (
            left_count,
            right_count,
            result_count,
            matched_count,
            exception_count,
            input_manifest_hash,
            result_set_hash,
            tenant,
            run,
        )
        if worker:
            completion_query = _RUN_COMPLETE_WITH_WORKER_QUERY
            completion_parameters += (worker,)
        else:
            completion_query = _RUN_COMPLETE_QUERY
        cursor = self.connection.execute(completion_query, completion_parameters)
        completed = self._record(cursor.fetchone(), self._RUN_COLUMNS)
        after_hash = self._hash_payload(completed)
        self._append_audit_outbox(
            tenant=tenant,
            action="run_completed",
            resource_id=run,
            before_state_hash=self._hash_payload(before),
            after_state_hash=after_hash,
            actor_id=actor_id,
            request_id=request_id,
            reason=reason,
            metadata={"left_input_count": left_count, "right_input_count": right_count, "result_count": result_count, "matched_count": matched_count, "exception_count": exception_count},
            payload={"run_id": run, "result_set_hash": result_set_hash, "input_manifest_hash": input_manifest_hash, "after_state_hash": after_hash},
        )
        return self.get_run(tenant_id=tenant, run_id=run)

    def iter_input_partitions(
        self,
        *,
        tenant_id: str,
        run_id: str,
        partition_fields: Sequence[str],
        amount_field: str = "amount",
        date_field: str = "date",
        reference_field: str = "reference",
        batch_size: int = 10_000,
    ) -> Iterator[tuple[tuple[str | None, ...], tuple[dict[str, Any], ...], tuple[dict[str, Any], ...]]]:
        """Stream one hard-key input partition at a time from PostgreSQL.

        The query uses a server-side cursor when psycopg provides one and
        orders by validated JSONB-derived partition values. Only the current
        partition is held in Python memory. The caller must keep this method
        inside the tenant-scoped transaction that owns the cursor.
        """

        tenant = self._tenant(tenant_id)
        run = self._id(run_id, "run_id")
        fields = tuple(self._text(value, "partition_field", maximum=128) for value in partition_fields)
        if not 1 <= len(fields) <= 8 or len(set(fields)) != len(fields):
            raise PostgresReconciliationValidationError(
                "partition_fields must contain between 1 and 8 unique names."
            )
        if isinstance(batch_size, bool) or not 1 <= int(batch_size) <= 100_000:
            raise PostgresReconciliationValidationError("batch_size must be between 1 and 100000.")
        amount_name = self._text(amount_field, "amount_field", maximum=128)
        date_name = self._text(date_field, "date_field", maximum=128)
        reference_name = self._text(reference_field, "reference_field", maximum=128)
        self._run_row(tenant, run)

        expressions: list[str] = []
        parameters: list[object] = []
        for position, field in enumerate(fields):
            partition_alias = "partition_value_" + str(position)
            expressions.append(
                
                    "CASE\n"
                    "    WHEN %s IN ('id', 'source_id') THEN source_id\n"
                    "    WHEN %s = 'currency_code' THEN currency_code\n"
                    "    WHEN %s = %s THEN COALESCE(amount_decimal::text, amount_original)\n"
                    "    WHEN %s = %s THEN COALESCE(date_value::text, date_original)\n"
                    "    WHEN %s = %s THEN COALESCE(NULLIF(reference_normalized, ''), reference_original)\n"
                    "    ELSE attributes_json ->> %s\n"
                    "END AS "
                    + partition_alias
                
            )
            parameters.extend(
                (
                    field,
                    field,
                    field,
                    amount_name,
                    field,
                    date_name,
                    field,
                    reference_name,
                    field,
                )
        )
        parameters.extend((tenant, run))
        partition_columns = ", ".join(expressions)
        partition_order = ", ".join("partition_value_" + str(index) + " NULLS FIRST" for index in range(len(fields)))
        query = (
            "SELECT tenant_id, run_id, side, source_id, record_hash, amount_decimal, "  # nosec
            "amount_original, currency_code, date_original, date_value, "
            "reference_original, reference_normalized, attributes_json, "
            f"valid, allowed_uses, created_at, {partition_columns} "
            f"FROM reconforge.reconciliation_inputs WHERE tenant_id = %s AND run_id = %s ORDER BY "
            f"{partition_order}, side, source_id"
        )
        cursor: Any
        cursor_factory = getattr(self.connection, "cursor", None)
        if callable(cursor_factory):
            cursor = cursor_factory(name=f"reconforge_inputs_{run[:48]}")
            cursor.execute(query, tuple(parameters))
        else:
            cursor = self.connection.execute(query, tuple(parameters))
        current_values: tuple[str | None, ...] | None = None
        left_records: list[dict[str, Any]] = []
        right_records: list[dict[str, Any]] = []
        try:
            while True:
                rows = cursor.fetchmany(int(batch_size))
                if not rows:
                    break
                for row in rows:
                    if isinstance(row, Mapping):
                        input_row = {column: row.get(column) for column in self._INPUT_COLUMNS}
                        values = tuple(
                            None if row.get(f"partition_value_{index}") is None else str(row.get(f"partition_value_{index}"))
                            for index in range(len(fields))
                        )
                    else:
                        row_values = tuple(row)
                        input_row = dict(zip(self._INPUT_COLUMNS, row_values[: len(self._INPUT_COLUMNS)], strict=True))
                        values = tuple(
                            None if item is None else str(item)
                            for item in row_values[len(self._INPUT_COLUMNS) :]
                        )
                    if len(values) != len(fields):
                        raise PostgresReconciliationIntegrityError(
                            "PostgreSQL partition cursor returned an unexpected shape."
                        )
                    if current_values is not None and values != current_values:
                        yield current_values, tuple(left_records), tuple(right_records)
                        left_records = []
                        right_records = []
                    current_values = values
                    if str(input_row["side"]) == "Left":
                        left_records.append(input_row)
                    elif str(input_row["side"]) == "Right":
                        right_records.append(input_row)
                    else:
                        raise PostgresReconciliationIntegrityError("PostgreSQL input cursor returned an invalid side.")
            if current_values is not None:
                yield current_values, tuple(left_records), tuple(right_records)
        finally:
            close = getattr(cursor, "close", None)
            if callable(close):
                close()

    def get_run(self, *, tenant_id: str, run_id: str) -> dict[str, Any]:
        """Return one run with deterministic child collections."""

        tenant = self._tenant(tenant_id)
        run = self._id(run_id, "run_id")
        record = self._run_row(tenant, run)
        record["inputs"] = self.list_inputs(tenant_id=tenant, run_id=run)
        record["results"] = self.list_results(tenant_id=tenant, run_id=run)
        record["exceptions"] = self.list_exceptions(tenant_id=tenant, run_id=run)
        return record

    def get_run_metadata(self, *, tenant_id: str, run_id: str) -> dict[str, Any]:
        """Return one run without eagerly loading potentially large child collections."""

        tenant = self._tenant(tenant_id)
        run = self._id(run_id, "run_id")
        return self._run_row(tenant, run)

    def list_inputs(
        self,
        *,
        tenant_id: str,
        run_id: str,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        tenant = self._tenant(tenant_id)
        run = self._id(run_id, "run_id")
        page_limit, page_offset = self._page(limit, offset)
        query = """
            SELECT tenant_id, run_id, side, source_id, record_hash, amount_decimal, amount_original,
                   currency_code, date_original, date_value, reference_original, reference_normalized,
                   attributes_json,
                   valid, allowed_uses, created_at
            FROM reconforge.reconciliation_inputs
            WHERE tenant_id = %s AND run_id = %s
            ORDER BY side, source_id
        """
        parameters: list[object] = [tenant, run]
        if page_limit is not None:
            query += " LIMIT %s OFFSET %s"
            parameters.extend((page_limit, page_offset))
        cursor = self.connection.execute(query, tuple(parameters))
        return [self._record(row, self._INPUT_COLUMNS) for row in cursor.fetchall()]

    def list_results(
        self,
        *,
        tenant_id: str,
        run_id: str,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        tenant = self._tenant(tenant_id)
        run = self._id(run_id, "run_id")
        page_limit, page_offset = self._page(limit, offset)
        query = """
            SELECT tenant_id, id, run_id, left_id, right_id, match_type, confidence, explanation,
                   amount_difference, date_difference_days, status, reason_code, lineage_json, created_at
            FROM reconforge.reconciliation_results
            WHERE tenant_id = %s AND run_id = %s
            ORDER BY left_id, right_id, match_type, id
        """
        parameters: list[object] = [tenant, run]
        if page_limit is not None:
            query += " LIMIT %s OFFSET %s"
            parameters.extend((page_limit, page_offset))
        cursor = self.connection.execute(query, tuple(parameters))
        return [self._record(row, self._RESULT_COLUMNS) for row in cursor.fetchall()]

    def list_exceptions(
        self,
        *,
        tenant_id: str,
        run_id: str,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        tenant = self._tenant(tenant_id)
        run = self._id(run_id, "run_id")
        page_limit, page_offset = self._page(limit, offset)
        query = """
            SELECT tenant_id, id, run_id, exception_type, source_side, source_id, title, explanation,
                   severity, risk_score, workflow_status, owner_id, reason_code, evidence_json,
                   created_at, updated_at
            FROM reconforge.reconciliation_exceptions
            WHERE tenant_id = %s AND run_id = %s
            ORDER BY severity DESC, source_side, source_id, id
        """
        parameters: list[object] = [tenant, run]
        if page_limit is not None:
            query += " LIMIT %s OFFSET %s"
            parameters.extend((page_limit, page_offset))
        cursor = self.connection.execute(query, tuple(parameters))
        return [self._record(row, self._EXCEPTION_COLUMNS) for row in cursor.fetchall()]


POSTGRES_RECONCILIATION_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS reconforge.reconciliation_runs (
    tenant_id TEXT NOT NULL,
    id TEXT NOT NULL,
    name TEXT NOT NULL,
    left_source TEXT NOT NULL,
    right_source TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Running',
    algorithm_version TEXT NOT NULL,
    rule_json JSONB NOT NULL,
    input_hash TEXT NOT NULL,
    idempotency_key TEXT,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    left_input_count BIGINT NOT NULL DEFAULT 0 CHECK (left_input_count >= 0),
    right_input_count BIGINT NOT NULL DEFAULT 0 CHECK (right_input_count >= 0),
    result_count BIGINT NOT NULL DEFAULT 0 CHECK (result_count >= 0),
    matched_count BIGINT NOT NULL DEFAULT 0 CHECK (matched_count >= 0),
    exception_count BIGINT NOT NULL DEFAULT 0 CHECK (exception_count >= 0),
    input_manifest_hash TEXT NOT NULL DEFAULT '',
    result_set_hash TEXT NOT NULL DEFAULT '',
    execution_status TEXT NOT NULL DEFAULT 'Queued',
    execution_worker_id TEXT,
    execution_claimed_at TIMESTAMPTZ,
    execution_lease_until TIMESTAMPTZ,
    execution_progress INTEGER NOT NULL DEFAULT 0 CHECK (execution_progress BETWEEN 0 AND 100),
    execution_attempt INTEGER NOT NULL DEFAULT 0 CHECK (execution_attempt >= 0),
    execution_started_at TIMESTAMPTZ,
    execution_finished_at TIMESTAMPTZ,
    execution_error TEXT NOT NULL DEFAULT '',
    cancel_requested BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, idempotency_key),
    FOREIGN KEY (tenant_id) REFERENCES reconforge.tenants(id) ON DELETE CASCADE,
    CHECK (status IN ('Running', 'Complete', 'Failed')),
    CHECK (execution_status IN ('Queued', 'Running', 'Complete', 'Failed', 'Cancelled'))
);

CREATE TABLE IF NOT EXISTS reconforge.reconciliation_inputs (
    tenant_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    side TEXT NOT NULL,
    source_id TEXT NOT NULL,
    record_hash TEXT NOT NULL,
    amount_decimal NUMERIC(38,18),
    amount_original TEXT NOT NULL DEFAULT '',
    currency_code TEXT NOT NULL DEFAULT '',
    date_original TEXT NOT NULL DEFAULT '',
    date_value DATE,
    reference_original TEXT NOT NULL DEFAULT '',
    reference_normalized TEXT NOT NULL DEFAULT '',
    attributes_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    valid BOOLEAN NOT NULL DEFAULT TRUE,
    allowed_uses INTEGER NOT NULL DEFAULT 1 CHECK (allowed_uses BETWEEN 1 AND 1000),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, run_id, side, source_id),
    FOREIGN KEY (tenant_id, run_id) REFERENCES reconforge.reconciliation_runs(tenant_id, id) ON DELETE CASCADE,
    CHECK (side IN ('Left', 'Right')),
    CHECK (currency_code = '' OR currency_code ~ '^[A-Z]{3}$')
);

CREATE TABLE IF NOT EXISTS reconforge.reconciliation_results (
    tenant_id TEXT NOT NULL,
    id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    left_id TEXT NOT NULL DEFAULT '',
    right_id TEXT NOT NULL DEFAULT '',
    match_type TEXT NOT NULL,
    confidence NUMERIC(12,8) NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    explanation TEXT NOT NULL,
    amount_difference NUMERIC(38,18) NOT NULL DEFAULT 0 CHECK (amount_difference >= 0),
    date_difference_days INTEGER,
    status TEXT NOT NULL,
    reason_code TEXT NOT NULL DEFAULT '',
    lineage_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    FOREIGN KEY (tenant_id, run_id) REFERENCES reconforge.reconciliation_runs(tenant_id, id) ON DELETE CASCADE,
    CHECK (left_id <> '' OR right_id <> ''),
    CHECK (status IN ('Matched', 'Unmatched', 'Invalid', 'Ambiguous', 'Duplicate', 'Rejected'))
);

CREATE TABLE IF NOT EXISTS reconforge.reconciliation_exceptions (
    tenant_id TEXT NOT NULL,
    id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    exception_type TEXT NOT NULL,
    source_side TEXT NOT NULL,
    source_id TEXT NOT NULL,
    title TEXT NOT NULL,
    explanation TEXT NOT NULL,
    severity TEXT NOT NULL,
    risk_score NUMERIC(12,8) NOT NULL CHECK (risk_score >= 0 AND risk_score <= 1),
    workflow_status TEXT NOT NULL DEFAULT 'Open',
    owner_id TEXT NOT NULL DEFAULT '',
    reason_code TEXT NOT NULL,
    evidence_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    FOREIGN KEY (tenant_id, run_id) REFERENCES reconforge.reconciliation_runs(tenant_id, id) ON DELETE CASCADE,
    CHECK (source_side IN ('Left', 'Right')),
    CHECK (severity IN ('Low', 'Medium', 'High', 'Critical')),
    CHECK (workflow_status IN ('Open', 'Assigned', 'Resolved', 'Accepted Risk', 'Closed'))
);

CREATE INDEX IF NOT EXISTS idx_reconciliation_runs_tenant_status
    ON reconforge.reconciliation_runs (tenant_id, status, created_at DESC, id);
CREATE INDEX IF NOT EXISTS idx_reconciliation_runs_execution_queue
    ON reconforge.reconciliation_runs (tenant_id, execution_status, execution_lease_until, created_at, id);
CREATE INDEX IF NOT EXISTS idx_reconciliation_inputs_run_side
    ON reconforge.reconciliation_inputs (tenant_id, run_id, side, source_id);
CREATE INDEX IF NOT EXISTS idx_reconciliation_results_run_status
    ON reconforge.reconciliation_results (tenant_id, run_id, status, left_id, right_id);
CREATE INDEX IF NOT EXISTS idx_reconciliation_exceptions_run_queue
    ON reconforge.reconciliation_exceptions (tenant_id, run_id, workflow_status, severity, source_id);

CREATE OR REPLACE FUNCTION reconforge.reject_completed_reconciliation_child_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $reconforge$
DECLARE
    target_tenant TEXT;
    target_run TEXT;
    run_status TEXT;
    run_execution_status TEXT;
BEGIN
    target_tenant := CASE WHEN TG_OP = 'DELETE' THEN OLD.tenant_id ELSE NEW.tenant_id END;
    target_run := CASE WHEN TG_OP = 'DELETE' THEN OLD.run_id ELSE NEW.run_id END;
    SELECT status, execution_status INTO run_status, run_execution_status
      FROM reconforge.reconciliation_runs
     WHERE tenant_id = target_tenant AND id = target_run;
    IF run_status <> 'Running' OR run_execution_status NOT IN ('Queued', 'Running') THEN
        RAISE EXCEPTION 'Completed reconciliation children are immutable' USING ERRCODE = '55000';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END
$reconforge$;

CREATE OR REPLACE FUNCTION reconforge.reject_reconciliation_run_delete()
RETURNS trigger
LANGUAGE plpgsql
AS $reconforge$
BEGIN
    RAISE EXCEPTION 'Reconciliation runs are append-only; do not delete financial results' USING ERRCODE = '55000';
END
$reconforge$;

CREATE OR REPLACE FUNCTION reconforge.reject_completed_reconciliation_run_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $reconforge$
BEGIN
    IF OLD.status <> 'Running' THEN
        RAISE EXCEPTION 'Completed reconciliation runs are immutable' USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END
$reconforge$;

DO $reconforge$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'reconciliation_inputs_immutable') THEN
        CREATE TRIGGER reconciliation_inputs_immutable
        BEFORE UPDATE OR DELETE ON reconforge.reconciliation_inputs
        FOR EACH ROW EXECUTE FUNCTION reconforge.reject_completed_reconciliation_child_mutation();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'reconciliation_results_immutable') THEN
        CREATE TRIGGER reconciliation_results_immutable
        BEFORE UPDATE OR DELETE ON reconforge.reconciliation_results
        FOR EACH ROW EXECUTE FUNCTION reconforge.reject_completed_reconciliation_child_mutation();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'reconciliation_exceptions_immutable') THEN
        CREATE TRIGGER reconciliation_exceptions_immutable
        BEFORE UPDATE OR DELETE ON reconforge.reconciliation_exceptions
        FOR EACH ROW EXECUTE FUNCTION reconforge.reject_completed_reconciliation_child_mutation();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'reconciliation_runs_no_delete') THEN
        CREATE TRIGGER reconciliation_runs_no_delete
        BEFORE DELETE ON reconforge.reconciliation_runs
        FOR EACH ROW EXECUTE FUNCTION reconforge.reject_reconciliation_run_delete();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'reconciliation_runs_immutable') THEN
        CREATE TRIGGER reconciliation_runs_immutable
        BEFORE UPDATE ON reconforge.reconciliation_runs
        FOR EACH ROW EXECUTE FUNCTION reconforge.reject_completed_reconciliation_run_mutation();
    END IF;
END
$reconforge$;

ALTER TABLE reconforge.reconciliation_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.reconciliation_runs FORCE ROW LEVEL SECURITY;
ALTER TABLE reconforge.reconciliation_inputs ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.reconciliation_inputs FORCE ROW LEVEL SECURITY;
ALTER TABLE reconforge.reconciliation_results ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.reconciliation_results FORCE ROW LEVEL SECURITY;
ALTER TABLE reconforge.reconciliation_exceptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.reconciliation_exceptions FORCE ROW LEVEL SECURITY;

DO $reconforge$
DECLARE
    table_name TEXT;
BEGIN
    FOREACH table_name IN ARRAY ARRAY['reconciliation_runs', 'reconciliation_inputs', 'reconciliation_results', 'reconciliation_exceptions']
    LOOP
        IF NOT EXISTS (
            SELECT 1 FROM pg_policies
             WHERE schemaname = 'reconforge' AND tablename = table_name AND policyname = 'tenant_scope'
        ) THEN
            EXECUTE format(
                'CREATE POLICY tenant_scope ON reconforge.%I USING (tenant_id = current_setting(''app.tenant_id'', true)) WITH CHECK (tenant_id = current_setting(''app.tenant_id'', true))',
                table_name
            );
        END IF;
    END LOOP;
END
$reconforge$;
"""
