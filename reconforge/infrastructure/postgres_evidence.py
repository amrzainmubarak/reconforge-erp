"""Tenant-scoped PostgreSQL evidence registry and coverage boundary.

The registry stores provenance and integrity metadata, not artifact bytes.  A
configured object-storage adapter owns the bytes; this repository records the
provider reference and refuses to mutate immutable artifact identity fields.
All writes are transaction-neutral and append audit/outbox evidence in the
caller's transaction.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from reconforge.infrastructure.postgres import PostgresConfigurationError, normalize_scope_id, validate_tenant_id
from reconforge.io.persisted import (
    PersistedJsonError,
    encode_audit_metadata,
    encode_postgres_outbox_payload,
)
from reconforge.utils.time import utc_now_text

_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_CODE_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9._/-]{0,63}$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_STORAGE_BACKENDS = ("local-filesystem", "s3-compatible-object-storage", "external-reference")
_VERIFICATION_STATUSES = ("Unverified", "Verified", "Failed")
_EVIDENCE_STATUSES = ("Available", "Quarantined", "Superseded")
_LIST_STATUSES = {"available", "quarantined", "superseded", "all"}
_LIST_EVIDENCE_COLUMNS = (
    "tenant_id",
    "id",
    "evidence_code",
    "source_name",
    "source_reference",
    "checksum_sha256",
    "provenance_type",
    "redaction_status",
    "evidence_status",
    "storage_backend",
    "storage_tenant_id",
    "storage_key",
    "storage_version_id",
    "content_type",
    "byte_size",
    "retention_until",
    "last_verified_at",
    "last_verified_sha256",
    "verification_status",
    "registered_by",
    "created_at",
    "updated_at",
)
_LIST_EVIDENCE_BASE_QUERY = (
    "SELECT tenant_id, id, evidence_code, source_name, source_reference, checksum_sha256,"
    " provenance_type, redaction_status, evidence_status, storage_backend,"
    " storage_tenant_id, storage_key, storage_version_id, content_type, byte_size,"
    " retention_until, last_verified_at, last_verified_sha256, verification_status,"
    " registered_by, created_at, updated_at "
    "FROM reconforge.evidence_registry "
    "WHERE tenant_id = %s "
)
_LIST_EVIDENCE_BY_STATUS: dict[str, str] = {
    "all": (
        _LIST_EVIDENCE_BASE_QUERY
        + "ORDER BY created_at DESC, id "
        + "LIMIT %s OFFSET %s"
    ),
    "available": (
        _LIST_EVIDENCE_BASE_QUERY
        + "AND evidence_status = %s "
        + "ORDER BY created_at DESC, id "
        + "LIMIT %s OFFSET %s"
    ),
    "quarantined": (
        _LIST_EVIDENCE_BASE_QUERY
        + "AND evidence_status = %s "
        + "ORDER BY created_at DESC, id "
        + "LIMIT %s OFFSET %s"
    ),
    "superseded": (
        _LIST_EVIDENCE_BASE_QUERY
        + "AND evidence_status = %s "
        + "ORDER BY created_at DESC, id "
        + "LIMIT %s OFFSET %s"
    ),
}


class PostgresEvidenceValidationError(ValueError):
    """Raised when evidence metadata fails validation."""


class PostgresEvidenceIntegrityError(RuntimeError):
    """Raised when evidence identity or persistence invariants are violated."""


class PostgresEvidenceNotFoundError(PostgresEvidenceIntegrityError):
    """Raised when a tenant-scoped evidence record does not exist."""


@dataclass(frozen=True)
class PostgresEvidenceVerification:
    """Provider checksum comparison recorded for one evidence object."""

    evidence_id: str
    ok: bool
    expected_sha256: str
    actual_sha256: str


def _tenant_id(value: object) -> str:
    try:
        return validate_tenant_id(str(value))
    except PostgresConfigurationError as exc:
        raise PostgresEvidenceValidationError(str(exc)) from exc


def _identifier(value: object, field_name: str) -> str:
    try:
        normalized = normalize_scope_id(str(value), field_name=field_name)
    except PostgresConfigurationError as exc:
        raise PostgresEvidenceValidationError(str(exc)) from exc
    if not _ID_PATTERN.fullmatch(normalized):
        raise PostgresEvidenceValidationError(f"{field_name} has an invalid identifier.")
    return normalized


def _text(value: object, field_name: str, *, maximum: int = 255, allow_blank: bool = False) -> str:
    normalized = str(value or "").strip()
    if not normalized and not allow_blank:
        raise PostgresEvidenceValidationError(f"{field_name} must not be blank.")
    if len(normalized) > maximum:
        raise PostgresEvidenceValidationError(f"{field_name} must be at most {maximum} characters.")
    if any(ord(character) < 32 or ord(character) == 127 for character in normalized):
        raise PostgresEvidenceValidationError(f"{field_name} must contain printable characters only.")
    return " ".join(normalized.split())


def _code(value: object, field_name: str = "evidence_code") -> str:
    normalized = _text(value, field_name, maximum=64).upper()
    if not _CODE_PATTERN.fullmatch(normalized):
        raise PostgresEvidenceValidationError(f"{field_name} has an invalid format.")
    return normalized


def _sha256(value: object, field_name: str) -> str:
    normalized = str(value or "").strip().lower()
    if not _SHA256_PATTERN.fullmatch(normalized):
        raise PostgresEvidenceValidationError(f"{field_name} must be a lowercase SHA-256 digest.")
    return normalized


def _choice(value: object, field_name: str, choices: tuple[str, ...]) -> str:
    normalized = _text(value, field_name, maximum=64).casefold()
    for choice in choices:
        if choice.casefold() == normalized:
            return choice
    raise PostgresEvidenceValidationError(f"{field_name} must be one of: {', '.join(choices)}.")


def _timestamp(value: object) -> str | None:
    if value is None or not str(value).strip():
        return None
    raw = str(value).strip()
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PostgresEvidenceValidationError("retention_until must be an ISO-8601 timestamp.") from exc
    if parsed.tzinfo is None:
        raise PostgresEvidenceValidationError("retention_until must include a timezone.")
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _storage_key(value: object, *, required: bool) -> str:
    normalized = _text(value, "storage_key", maximum=1_024, allow_blank=not required)
    if normalized and (normalized.startswith(("/", "\\")) or "\\" in normalized or ".." in normalized.split("/")):
        raise PostgresEvidenceValidationError("storage_key must be a tenant-relative safe path.")
    return normalized


def _json_text(value: Mapping[str, object] | None, field_name: str) -> str:
    try:
        return encode_audit_metadata(value).text
    except PersistedJsonError as exc:
        raise PostgresEvidenceValidationError(f"{field_name} must be JSON-serializable.") from exc


def _outbox_json_text(value: Mapping[str, object]) -> str:
    try:
        return encode_postgres_outbox_payload(value).text
    except PersistedJsonError as exc:
        raise PostgresEvidenceValidationError("outbox payload must be JSON-serializable.") from exc


def _row_value(row: Any, key: str, index: int) -> Any:
    if isinstance(row, Mapping):
        return row.get(key)
    return row[index]


def _record(row: Any, columns: tuple[str, ...]) -> dict[str, Any]:
    if row is None:
        raise PostgresEvidenceIntegrityError("PostgreSQL evidence operation returned no record.")
    if isinstance(row, Mapping):
        return {str(key): value for key, value in row.items()}
    values = tuple(row)
    if len(values) != len(columns):
        raise PostgresEvidenceIntegrityError("PostgreSQL evidence record shape was unexpected.")
    return dict(zip(columns, values, strict=True))


def _hash_payload(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(dict(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PostgresEvidenceRepository:
    """Read and write immutable-reference evidence records without committing."""

    connection: Any

    _COLUMNS = (
        "tenant_id",
        "id",
        "evidence_code",
        "source_name",
        "source_reference",
        "checksum_sha256",
        "provenance_type",
        "redaction_status",
        "evidence_status",
        "storage_backend",
        "storage_tenant_id",
        "storage_key",
        "storage_version_id",
        "content_type",
        "byte_size",
        "retention_until",
        "last_verified_at",
        "last_verified_sha256",
        "verification_status",
        "registered_by",
        "created_at",
        "updated_at",
    )
    _LINK_COLUMNS = ("tenant_id", "id", "evidence_id", "object_type", "object_id", "link_type", "created_at")
    _REQUIREMENT_COLUMNS = (
        "tenant_id",
        "id",
        "object_type",
        "object_id",
        "requirement_code",
        "description",
        "required_status",
        "created_at",
        "updated_at",
    )

    def _get_row(self, tenant: str, evidence_id: str) -> dict[str, Any]:
        cursor = self.connection.execute(
            """
            SELECT tenant_id, id, evidence_code, source_name, source_reference, checksum_sha256,
                   provenance_type, redaction_status, evidence_status, storage_backend,
                   storage_tenant_id, storage_key, storage_version_id, content_type, byte_size,
                   retention_until, last_verified_at, last_verified_sha256, verification_status,
                   registered_by, created_at, updated_at
            FROM reconforge.evidence_registry
            WHERE tenant_id = %s AND id = %s
            """,
            (tenant, evidence_id),
        )
        row = cursor.fetchone()
        if row is None:
            raise PostgresEvidenceNotFoundError("Evidence record was not found.")
        return _record(row, self._COLUMNS)

    def _append_audit_outbox(
        self,
        *,
        tenant: str,
        action: str,
        resource_type: str,
        resource_id: str,
        before_state_hash: str,
        after_state_hash: str,
        actor_id: str,
        request_id: str,
        reason: str,
        metadata: Mapping[str, object] | None,
        payload: Mapping[str, object],
    ) -> None:
        actor = _text(actor_id, "actor_id", maximum=160)
        request = _text(request_id, "request_id", maximum=160, allow_blank=True)
        audit_reason = _text(reason, "reason", maximum=500, allow_blank=True)
        metadata_json = _json_text(metadata, "metadata")
        payload_json = _outbox_json_text(payload)
        self.connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (tenant,))
        audit_event_id = _hash_payload(
            {"tenant_id": tenant, "action": action, "resource_id": resource_id, "after_state_hash": after_state_hash}
        )
        previous_cursor = self.connection.execute(
            "SELECT event_hash FROM reconforge.audit_events WHERE tenant_id = %s ORDER BY event_sequence DESC LIMIT 1",
            (tenant,),
        )
        previous_row = previous_cursor.fetchone()
        previous_hash = "" if previous_row is None else str(_row_value(previous_row, "event_hash", 0) or "")
        occurred_at = utc_now_text()
        event_hash = _hash_payload(
            {
                "tenant_id": tenant,
                "event_id": audit_event_id,
                "actor_id": actor,
                "action": action,
                "resource_type": resource_type,
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
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CAST(%s AS jsonb))
            ON CONFLICT (tenant_id, event_id) DO NOTHING
            """,
            (
                tenant,
                audit_event_id,
                actor,
                action,
                resource_type,
                resource_id,
                occurred_at,
                request,
                before_state_hash,
                after_state_hash,
                previous_hash,
                event_hash,
                audit_reason,
                metadata_json,
            ),
        )
        outbox_event_id = _hash_payload({"tenant_id": tenant, "event_type": f"evidence.{action}", "resource_id": resource_id})
        self.connection.execute(
            """
            INSERT INTO reconforge.outbox_events
                (tenant_id, event_id, event_type, aggregate_type, aggregate_id, payload)
            VALUES (%s, %s, %s, %s, %s, CAST(%s AS jsonb))
            ON CONFLICT (tenant_id, event_id) DO NOTHING
            """,
            (tenant, outbox_event_id, f"evidence.{action}", resource_type, resource_id, payload_json),
        )

    def register(
        self,
        *,
        tenant_id: str,
        evidence_id: str,
        evidence_code: str,
        source_name: str,
        checksum_sha256: str,
        actor_id: str,
        source_reference: str = "",
        provenance_type: str = "external-reference",
        redaction_status: str = "unknown",
        evidence_status: str = "Available",
        storage_backend: str = "external-reference",
        storage_tenant_id: str = "",
        storage_key: str = "",
        storage_version_id: str = "",
        content_type: str = "application/octet-stream",
        byte_size: int = 0,
        retention_until: object | None = None,
        request_id: str = "",
        reason: str = "",
        metadata: Mapping[str, object] | None = None,
    ) -> dict[str, Any]:
        """Create or idempotently update one evidence metadata record."""

        tenant = _tenant_id(tenant_id)
        identifier = _identifier(evidence_id, "evidence_id")
        code = _code(evidence_code)
        name = _text(source_name, "source_name", maximum=512)
        source = _text(source_reference, "source_reference", maximum=2_048, allow_blank=True)
        digest = _sha256(checksum_sha256, "checksum_sha256")
        provenance = _text(provenance_type, "provenance_type", maximum=64)
        redaction = _text(redaction_status, "redaction_status", maximum=64)
        status = _choice(evidence_status, "evidence_status", _EVIDENCE_STATUSES)
        backend = _choice(storage_backend, "storage_backend", _STORAGE_BACKENDS)
        storage_tenant = _tenant_id(storage_tenant_id or tenant) if backend != "local-filesystem" else ""
        if backend != "local-filesystem" and storage_tenant != tenant:
            raise PostgresEvidenceValidationError("storage_tenant_id must equal tenant_id for hosted evidence.")
        key = _storage_key(storage_key, required=backend != "external-reference")
        version = _text(storage_version_id, "storage_version_id", maximum=255, allow_blank=True)
        content = _text(content_type, "content_type", maximum=255)
        try:
            size = int(byte_size)
        except (TypeError, ValueError) as exc:
            raise PostgresEvidenceValidationError("byte_size must be an integer.") from exc
        if size < 0 or size > 10**12:
            raise PostgresEvidenceValidationError("byte_size is outside the supported range.")
        retention = _timestamp(retention_until)
        before_cursor = self.connection.execute(
            """
            SELECT tenant_id, id, evidence_code, source_name, source_reference, checksum_sha256,
                   provenance_type, redaction_status, evidence_status, storage_backend,
                   storage_tenant_id, storage_key, storage_version_id, content_type, byte_size,
                   retention_until, last_verified_at, last_verified_sha256, verification_status,
                   registered_by, created_at, updated_at
            FROM reconforge.evidence_registry
            WHERE tenant_id = %s AND (id = %s OR evidence_code = %s)
            FOR UPDATE
            """,
            (tenant, identifier, code),
        )
        before_row = before_cursor.fetchone()
        before = None if before_row is None else _record(before_row, self._COLUMNS)
        if before is not None:
            if str(before["id"]) != identifier or str(before["checksum_sha256"]) != digest:
                raise PostgresEvidenceIntegrityError("Evidence code or identifier already refers to different artifact content.")
            immutable_pairs = (
                ("storage_backend", backend),
                ("storage_tenant_id", storage_tenant),
                ("storage_key", key),
                ("storage_version_id", version),
            )
            if any(str(before[field]) != value for field, value in immutable_pairs):
                raise PostgresEvidenceIntegrityError("Stored evidence artifact references are immutable.")
            cursor = self.connection.execute(
                """
                UPDATE reconforge.evidence_registry
                SET source_name = %s, source_reference = %s, provenance_type = %s,
                    redaction_status = %s, evidence_status = %s, content_type = %s,
                    byte_size = %s, retention_until = %s, registered_by = %s, updated_at = now()
                WHERE tenant_id = %s AND id = %s
                RETURNING tenant_id, id, evidence_code, source_name, source_reference, checksum_sha256,
                          provenance_type, redaction_status, evidence_status, storage_backend,
                          storage_tenant_id, storage_key, storage_version_id, content_type, byte_size,
                          retention_until, last_verified_at, last_verified_sha256, verification_status,
                          registered_by, created_at, updated_at
                """,
                (name, source, provenance, redaction, status, content, size, retention, actor_id, tenant, identifier),
            )
            action = "evidence_metadata_updated"
        else:
            cursor = self.connection.execute(
                """
                INSERT INTO reconforge.evidence_registry
                    (tenant_id, id, evidence_code, source_name, source_reference, checksum_sha256,
                     provenance_type, redaction_status, evidence_status, storage_backend,
                     storage_tenant_id, storage_key, storage_version_id, content_type, byte_size,
                     retention_until, registered_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING tenant_id, id, evidence_code, source_name, source_reference, checksum_sha256,
                          provenance_type, redaction_status, evidence_status, storage_backend,
                          storage_tenant_id, storage_key, storage_version_id, content_type, byte_size,
                          retention_until, last_verified_at, last_verified_sha256, verification_status,
                          registered_by, created_at, updated_at
                """,
                (
                    tenant,
                    identifier,
                    code,
                    name,
                    source,
                    digest,
                    provenance,
                    redaction,
                    status,
                    backend,
                    storage_tenant,
                    key,
                    version,
                    content,
                    size,
                    retention,
                    _text(actor_id, "actor_id", maximum=160),
                ),
            )
            action = "evidence_registered"
        record = _record(cursor.fetchone(), self._COLUMNS)
        before_hash = "" if before is None else _hash_payload(before)
        after_hash = _hash_payload(record)
        self._append_audit_outbox(
            tenant=tenant,
            action=action,
            resource_type="evidence",
            resource_id=identifier,
            before_state_hash=before_hash,
            after_state_hash=after_hash,
            actor_id=actor_id,
            request_id=request_id,
            reason=reason,
            metadata=metadata,
            payload={"evidence_id": identifier, "checksum_sha256": digest, "storage_backend": backend, "after_state_hash": after_hash},
        )
        return self.get(tenant_id=tenant, evidence_id=identifier)

    def get(self, *, tenant_id: str, evidence_id: str) -> dict[str, Any]:
        """Return one evidence record with its tenant-scoped links."""

        tenant = _tenant_id(tenant_id)
        identifier = _identifier(evidence_id, "evidence_id")
        record = self._get_row(tenant, identifier)
        links_cursor = self.connection.execute(
            """
            SELECT tenant_id, id, evidence_id, object_type, object_id, link_type, created_at
            FROM reconforge.evidence_links
            WHERE tenant_id = %s AND evidence_id = %s
            ORDER BY object_type, object_id, link_type, id
            """,
            (tenant, identifier),
        )
        record["links"] = [_record(row, self._LINK_COLUMNS) for row in links_cursor.fetchall()]
        return record

    def list_evidence(self, *, tenant_id: str, status: str = "all", limit: int = 500, offset: int = 0) -> list[dict[str, Any]]:
        """List tenant evidence in deterministic order."""

        tenant = _tenant_id(tenant_id)
        selected_status = str(status or "all").strip().casefold()
        if selected_status not in _LIST_STATUSES:
            raise PostgresEvidenceValidationError("status must be available, quarantined, superseded, or all.")
        if not 1 <= int(limit) <= 10_000:
            raise PostgresEvidenceValidationError("limit must be between 1 and 10000.")
        if not 0 <= int(offset) <= 10_000_000:
            raise PostgresEvidenceValidationError("offset must be between 0 and 10000000.")
        if selected_status == "all":
            query = _LIST_EVIDENCE_BY_STATUS["all"]
            cursor = self.connection.execute(
                query,
                (tenant, int(limit), int(offset)),
            )
        else:
            normalized_status = _choice(selected_status, "evidence_status", _EVIDENCE_STATUSES)
            query = _LIST_EVIDENCE_BY_STATUS[selected_status]
            cursor = self.connection.execute(
                query,
                (tenant, normalized_status, int(limit), int(offset)),
            )
        return [_record(row, self._COLUMNS) for row in cursor.fetchall()]

    def link(
        self,
        *,
        tenant_id: str,
        evidence_id: str,
        object_type: str,
        object_id: str,
        actor_id: str,
        link_type: str = "support",
        request_id: str = "",
        reason: str = "",
        metadata: Mapping[str, object] | None = None,
    ) -> dict[str, Any]:
        """Link evidence to a tenant-scoped reconciliation, control, or workflow object."""

        tenant = _tenant_id(tenant_id)
        evidence = _identifier(evidence_id, "evidence_id")
        self._get_row(tenant, evidence)
        target_type = _text(object_type, "object_type", maximum=100)
        target_id = _text(object_id, "object_id", maximum=160)
        selected_link_type = _text(link_type, "link_type", maximum=64)
        link_id = "evl-" + _hash_payload(
            {"tenant_id": tenant, "evidence_id": evidence, "object_type": target_type, "object_id": target_id, "link_type": selected_link_type}
        )[:48]
        cursor = self.connection.execute(
            """
            INSERT INTO reconforge.evidence_links
                (tenant_id, id, evidence_id, object_type, object_id, link_type)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id, evidence_id, object_type, object_id, link_type) DO NOTHING
            RETURNING tenant_id, id, evidence_id, object_type, object_id, link_type, created_at
            """,
            (tenant, link_id, evidence, target_type, target_id, selected_link_type),
        )
        row = cursor.fetchone()
        if row is None:
            cursor = self.connection.execute(
                """
                SELECT tenant_id, id, evidence_id, object_type, object_id, link_type, created_at
                FROM reconforge.evidence_links
                WHERE tenant_id = %s AND id = %s
                """,
                (tenant, link_id),
            )
            row = cursor.fetchone()
        link_record = _record(row, self._LINK_COLUMNS)
        link_hash = _hash_payload(link_record)
        self._append_audit_outbox(
            tenant=tenant,
            action="evidence_linked",
            resource_type="evidence_link",
            resource_id=link_id,
            before_state_hash="",
            after_state_hash=link_hash,
            actor_id=actor_id,
            request_id=request_id,
            reason=reason,
            metadata=metadata,
            payload={"evidence_id": evidence, "object_type": target_type, "object_id": target_id, "after_state_hash": link_hash},
        )
        return link_record

    def requirement(
        self,
        *,
        tenant_id: str,
        object_type: str,
        object_id: str,
        requirement_code: str,
        description: str,
        actor_id: str,
        required_status: str = "Required",
        request_id: str = "",
        reason: str = "",
        metadata: Mapping[str, object] | None = None,
    ) -> dict[str, Any]:
        """Create or update one evidence requirement."""

        tenant = _tenant_id(tenant_id)
        target_type = _text(object_type, "object_type", maximum=100)
        target_id = _text(object_id, "object_id", maximum=160)
        code = _code(requirement_code, "requirement_code")
        details = _text(description, "description", maximum=2_000)
        status = _text(required_status, "required_status", maximum=64)
        requirement_id = "evreq-" + _hash_payload(
            {"tenant_id": tenant, "object_type": target_type, "object_id": target_id, "requirement_code": code}
        )[:48]
        before_cursor = self.connection.execute(
            """
            SELECT tenant_id, id, object_type, object_id, requirement_code, description,
                   required_status, created_at, updated_at
            FROM reconforge.evidence_requirements
            WHERE tenant_id = %s AND id = %s
            FOR UPDATE
            """,
            (tenant, requirement_id),
        )
        before_row = before_cursor.fetchone()
        before = None if before_row is None else _record(before_row, self._REQUIREMENT_COLUMNS)
        cursor = self.connection.execute(
            """
            INSERT INTO reconforge.evidence_requirements
                (tenant_id, id, object_type, object_id, requirement_code, description, required_status)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id, object_type, object_id, requirement_code)
            DO UPDATE SET description = EXCLUDED.description, required_status = EXCLUDED.required_status,
                          updated_at = now()
            RETURNING tenant_id, id, object_type, object_id, requirement_code, description,
                      required_status, created_at, updated_at
            """,
            (tenant, requirement_id, target_type, target_id, code, details, status),
        )
        record = _record(cursor.fetchone(), self._REQUIREMENT_COLUMNS)
        after_hash = _hash_payload(record)
        self._append_audit_outbox(
            tenant=tenant,
            action="evidence_requirement_saved",
            resource_type="evidence_requirement",
            resource_id=requirement_id,
            before_state_hash="" if before is None else _hash_payload(before),
            after_state_hash=after_hash,
            actor_id=actor_id,
            request_id=request_id,
            reason=reason,
            metadata=metadata,
            payload={"object_type": target_type, "object_id": target_id, "requirement_code": code, "after_state_hash": after_hash},
        )
        return record

    def verify_checksum(
        self,
        *,
        tenant_id: str,
        evidence_id: str,
        actual_sha256: str,
        actor_id: str,
        request_id: str = "",
        reason: str = "",
        metadata: Mapping[str, object] | None = None,
    ) -> PostgresEvidenceVerification:
        """Record a provider-computed checksum comparison atomically."""

        tenant = _tenant_id(tenant_id)
        identifier = _identifier(evidence_id, "evidence_id")
        actual = _sha256(actual_sha256, "actual_sha256")
        before = self._get_row(tenant, identifier)
        expected = str(before["checksum_sha256"])
        ok = expected == actual
        cursor = self.connection.execute(
            """
            UPDATE reconforge.evidence_registry
            SET last_verified_at = now(), last_verified_sha256 = %s,
                verification_status = %s, updated_at = now()
            WHERE tenant_id = %s AND id = %s
            RETURNING tenant_id, id, evidence_code, source_name, source_reference, checksum_sha256,
                      provenance_type, redaction_status, evidence_status, storage_backend,
                      storage_tenant_id, storage_key, storage_version_id, content_type, byte_size,
                      retention_until, last_verified_at, last_verified_sha256, verification_status,
                      registered_by, created_at, updated_at
            """,
            (actual, "Verified" if ok else "Failed", tenant, identifier),
        )
        after = _record(cursor.fetchone(), self._COLUMNS)
        after_hash = _hash_payload(after)
        self._append_audit_outbox(
            tenant=tenant,
            action="evidence_checksum_verified",
            resource_type="evidence",
            resource_id=identifier,
            before_state_hash=_hash_payload(before),
            after_state_hash=after_hash,
            actor_id=actor_id,
            request_id=request_id,
            reason=reason,
            metadata={**dict(metadata or {}), "ok": ok, "actual_sha256": actual},
            payload={"evidence_id": identifier, "ok": ok, "expected_sha256": expected, "actual_sha256": actual, "after_state_hash": after_hash},
        )
        return PostgresEvidenceVerification(evidence_id=identifier, ok=ok, expected_sha256=expected, actual_sha256=actual)

    def coverage(self, *, tenant_id: str) -> dict[str, Any]:
        """Return tenant-scoped evidence requirement coverage."""

        tenant = _tenant_id(tenant_id)
        cursor = self.connection.execute(
            """
            SELECT requirement.object_type, requirement.object_id,
                   COUNT(DISTINCT requirement.id) AS requirement_count,
                   COUNT(DISTINCT link.evidence_id) AS linked_evidence_count
            FROM reconforge.evidence_requirements AS requirement
            LEFT JOIN reconforge.evidence_links AS link
              ON link.tenant_id = requirement.tenant_id
             AND link.object_type = requirement.object_type
             AND link.object_id = requirement.object_id
            WHERE requirement.tenant_id = %s
            GROUP BY requirement.object_type, requirement.object_id
            ORDER BY requirement.object_type, requirement.object_id
            """,
            (tenant,),
        )
        objects: list[dict[str, Any]] = [
            {
                "object_type": str(_row_value(row, "object_type", 0)),
                "object_id": str(_row_value(row, "object_id", 1)),
                "requirement_count": int(_row_value(row, "requirement_count", 2) or 0),
                "linked_evidence_count": int(_row_value(row, "linked_evidence_count", 3) or 0),
            }
            for row in cursor.fetchall()
        ]
        requirement_count = sum(int(item["requirement_count"]) for item in objects)
        covered_count = sum(1 for item in objects if int(item["linked_evidence_count"]) > 0)
        return {
            "tenant_id": tenant,
            "object_count": len(objects),
            "requirement_count": requirement_count,
            "covered_object_count": covered_count,
            "coverage_pct": round((covered_count / len(objects)) * 100, 2) if objects else 100.0,
            "objects": objects,
        }


POSTGRES_EVIDENCE_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS reconforge.evidence_registry (
    tenant_id TEXT NOT NULL,
    id TEXT NOT NULL,
    evidence_code TEXT NOT NULL,
    source_name TEXT NOT NULL,
    source_reference TEXT NOT NULL DEFAULT '',
    checksum_sha256 TEXT NOT NULL,
    provenance_type TEXT NOT NULL,
    redaction_status TEXT NOT NULL,
    evidence_status TEXT NOT NULL DEFAULT 'Available',
    storage_backend TEXT NOT NULL DEFAULT 'external-reference',
    storage_tenant_id TEXT NOT NULL DEFAULT '',
    storage_key TEXT NOT NULL DEFAULT '',
    storage_version_id TEXT NOT NULL DEFAULT '',
    content_type TEXT NOT NULL DEFAULT 'application/octet-stream',
    byte_size BIGINT NOT NULL DEFAULT 0 CHECK (byte_size >= 0),
    retention_until TIMESTAMPTZ,
    last_verified_at TIMESTAMPTZ,
    last_verified_sha256 TEXT,
    verification_status TEXT NOT NULL DEFAULT 'Unverified',
    registered_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, evidence_code),
    FOREIGN KEY (tenant_id) REFERENCES reconforge.tenants(id) ON DELETE CASCADE,
    CHECK (checksum_sha256 ~ '^[0-9a-f]{64}$'),
    CHECK (last_verified_sha256 IS NULL OR last_verified_sha256 ~ '^[0-9a-f]{64}$'),
    CHECK (evidence_status IN ('Available', 'Quarantined', 'Superseded')),
    CHECK (verification_status IN ('Unverified', 'Verified', 'Failed')),
    CHECK (storage_backend IN ('local-filesystem', 's3-compatible-object-storage', 'external-reference'))
);

CREATE TABLE IF NOT EXISTS reconforge.evidence_links (
    tenant_id TEXT NOT NULL,
    id TEXT NOT NULL,
    evidence_id TEXT NOT NULL,
    object_type TEXT NOT NULL,
    object_id TEXT NOT NULL,
    link_type TEXT NOT NULL DEFAULT 'support',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, evidence_id, object_type, object_id, link_type),
    FOREIGN KEY (tenant_id, evidence_id) REFERENCES reconforge.evidence_registry(tenant_id, id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS reconforge.evidence_requirements (
    tenant_id TEXT NOT NULL,
    id TEXT NOT NULL,
    object_type TEXT NOT NULL,
    object_id TEXT NOT NULL,
    requirement_code TEXT NOT NULL,
    description TEXT NOT NULL,
    required_status TEXT NOT NULL DEFAULT 'Required',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, object_type, object_id, requirement_code),
    FOREIGN KEY (tenant_id) REFERENCES reconforge.tenants(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_evidence_registry_tenant_status
    ON reconforge.evidence_registry (tenant_id, evidence_status, created_at DESC, id);
CREATE INDEX IF NOT EXISTS idx_evidence_registry_storage
    ON reconforge.evidence_registry (tenant_id, storage_backend, storage_tenant_id, storage_key);
CREATE INDEX IF NOT EXISTS idx_evidence_links_object
    ON reconforge.evidence_links (tenant_id, object_type, object_id, evidence_id);
CREATE INDEX IF NOT EXISTS idx_evidence_requirements_object
    ON reconforge.evidence_requirements (tenant_id, object_type, object_id, requirement_code);

CREATE OR REPLACE FUNCTION reconforge.reject_evidence_artifact_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $reconforge$
BEGIN
    IF OLD.checksum_sha256 <> NEW.checksum_sha256
       OR OLD.storage_backend <> NEW.storage_backend
       OR OLD.storage_tenant_id <> NEW.storage_tenant_id
       OR OLD.storage_key <> NEW.storage_key
       OR OLD.storage_version_id <> NEW.storage_version_id THEN
        RAISE EXCEPTION 'Evidence artifact identity is immutable' USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END
$reconforge$;

CREATE OR REPLACE FUNCTION reconforge.reject_evidence_delete()
RETURNS trigger
LANGUAGE plpgsql
AS $reconforge$
BEGIN
    RAISE EXCEPTION 'Evidence records are append-only; supersede instead of deleting' USING ERRCODE = '55000';
END
$reconforge$;

DO $reconforge$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'evidence_artifact_immutable') THEN
        CREATE TRIGGER evidence_artifact_immutable
        BEFORE UPDATE ON reconforge.evidence_registry
        FOR EACH ROW EXECUTE FUNCTION reconforge.reject_evidence_artifact_mutation();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'evidence_registry_no_delete') THEN
        CREATE TRIGGER evidence_registry_no_delete
        BEFORE DELETE ON reconforge.evidence_registry
        FOR EACH ROW EXECUTE FUNCTION reconforge.reject_evidence_delete();
    END IF;
END
$reconforge$;

ALTER TABLE reconforge.evidence_registry ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.evidence_registry FORCE ROW LEVEL SECURITY;
ALTER TABLE reconforge.evidence_links ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.evidence_links FORCE ROW LEVEL SECURITY;
ALTER TABLE reconforge.evidence_requirements ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.evidence_requirements FORCE ROW LEVEL SECURITY;

DO $reconforge$
DECLARE
    table_name TEXT;
BEGIN
    FOREACH table_name IN ARRAY ARRAY['evidence_registry', 'evidence_links', 'evidence_requirements']
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
