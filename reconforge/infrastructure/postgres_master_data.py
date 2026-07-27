"""PostgreSQL master-data repository for the optional server deployment.

This is intentionally a small, explicit server-side bounded context.  It is
not a wrapper around the SQLite ``MasterDataService``: SQL, constraints, and
tenant isolation are implemented by PostgreSQL itself.  Callers must use
``PostgresTenantBoundary`` (or an equivalent transaction boundary) before
using this repository.  The repository never commits or changes transaction
ownership.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

from reconforge.infrastructure.postgres import PostgresConfigurationError, normalize_scope_id, validate_tenant_id
from reconforge.io.persisted import (
    PersistedJsonError,
    encode_audit_metadata,
    encode_postgres_outbox_payload,
)
from reconforge.utils.time import utc_now_text

_CODE_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9_-]{0,63}$")
_CURRENCY_PATTERN = re.compile(r"^[A-Z]{3}$")
_MAX_NAME_LENGTH = 255
_PERIOD_STATUSES = ("Open", "Soft Closed", "Closed")
_PERIOD_TRANSITIONS = {
    "Open": {"Soft Closed"},
    "Soft Closed": {"Open", "Closed"},
    "Closed": {"Open"},
}
_BEFORE_STATE_HASH_QUERIES: dict[str, tuple[str, tuple[str, ...]]] = {
    "currencies": (
        "SELECT tenant_id, code, name, minor_units, active FROM reconforge.currencies WHERE tenant_id = %s AND code = %s",
        ("tenant_id", "code", "name", "minor_units", "active"),
    ),
    "organizations": (
        "SELECT tenant_id, id, organization_code, name, base_currency, active, created_at, updated_at "
        "FROM reconforge.organizations WHERE tenant_id = %s AND id = %s",
        ("tenant_id", "id", "organization_code", "name", "base_currency", "active", "created_at", "updated_at"),
    ),
    "legal_entities": (
        "SELECT tenant_id, id, organization_id, entity_code, name, currency_code, active, created_at, updated_at "
        "FROM reconforge.legal_entities WHERE tenant_id = %s AND id = %s",
        ("tenant_id", "id", "organization_id", "entity_code", "name", "currency_code", "active", "created_at", "updated_at"),
    ),
    "branches": (
        "SELECT tenant_id, id, organization_id, legal_entity_id, branch_code, name, active, created_at, updated_at "
        "FROM reconforge.branches WHERE tenant_id = %s AND id = %s",
        ("tenant_id", "id", "organization_id", "legal_entity_id", "branch_code", "name", "active", "created_at", "updated_at"),
    ),
    "fiscal_periods": (
        "SELECT tenant_id, id, name, start_date, end_date, status, created_at, fiscal_year, period_number, "
        "status_reason, updated_at FROM reconforge.fiscal_periods WHERE tenant_id = %s AND id = %s",
        (
            "tenant_id",
            "id",
            "name",
            "start_date",
            "end_date",
            "status",
            "fiscal_year",
            "period_number",
            "status_reason",
            "created_at",
            "updated_at",
        ),
    ),
}


class PostgresMasterDataValidationError(ValueError):
    """Raised when a master-data value cannot be safely persisted."""


class PostgresMasterDataError(RuntimeError):
    """Raised for repository-level failures with safe, non-sensitive text."""


def _required_text(value: str, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise PostgresMasterDataValidationError(f"{field_name} must not be blank.")
    if len(normalized) > _MAX_NAME_LENGTH:
        raise PostgresMasterDataValidationError(f"{field_name} must be at most {_MAX_NAME_LENGTH} characters.")
    return normalized


def _code(value: str, field_name: str) -> str:
    normalized = _required_text(value, field_name).upper()
    if not _CODE_PATTERN.fullmatch(normalized):
        raise PostgresMasterDataValidationError(
            f"{field_name} must use 1-64 uppercase letters, numbers, hyphens, or underscores."
        )
    return normalized


def _currency_code(value: str, field_name: str = "currency_code") -> str:
    normalized = _required_text(value, field_name).upper()
    if not _CURRENCY_PATTERN.fullmatch(normalized):
        raise PostgresMasterDataValidationError(f"{field_name} must be a three-letter ISO-style code.")
    return normalized


def _iso_date(value: str, field_name: str) -> str:
    normalized = str(value or "").strip()
    try:
        parsed = date.fromisoformat(normalized)
    except ValueError as exc:
        raise PostgresMasterDataValidationError(
            f"{field_name} must be an ISO date in YYYY-MM-DD format."
        ) from exc
    if parsed.isoformat() != normalized:
        raise PostgresMasterDataValidationError(f"{field_name} must be an ISO date in YYYY-MM-DD format.")
    return normalized


def _period_status(value: str) -> str:
    normalized = " ".join(str(value or "").strip().title().split())
    if normalized not in _PERIOD_STATUSES:
        raise PostgresMasterDataValidationError(
            f"Period status must be one of: {', '.join(_PERIOD_STATUSES)}."
        )
    return normalized


def _period_reason(value: str) -> str:
    normalized = " ".join(str(value or "").strip().split())
    if any(ord(character) < 32 or ord(character) == 127 for character in normalized):
        raise PostgresMasterDataValidationError("Period status reason must contain printable characters only.")
    if len(normalized) > 500:
        raise PostgresMasterDataValidationError("Period status reason must not exceed 500 characters.")
    return normalized


def _optional_scope_id(value: str | None, field_name: str) -> str | None:
    if value is None or not str(value).strip():
        return None
    try:
        return normalize_scope_id(value, field_name=field_name)
    except PostgresConfigurationError as exc:
        raise PostgresMasterDataValidationError(str(exc)) from exc


def _tenant_id(value: str) -> str:
    try:
        return validate_tenant_id(value)
    except PostgresConfigurationError as exc:
        raise PostgresMasterDataValidationError(str(exc)) from exc


def _scope_id(value: str, field_name: str) -> str:
    try:
        return normalize_scope_id(value, field_name=field_name)
    except PostgresConfigurationError as exc:
        raise PostgresMasterDataValidationError(str(exc)) from exc


def _record(row: Any, columns: tuple[str, ...]) -> dict[str, Any]:
    if isinstance(row, Mapping):
        return {str(key): value for key, value in row.items()}
    if row is None:
        raise PostgresMasterDataError("PostgreSQL master-data write returned no record.")
    values = tuple(row)
    if len(values) != len(columns):
        raise PostgresMasterDataError("PostgreSQL master-data record shape was unexpected.")
    return dict(zip(columns, values, strict=True))


def _records(rows: list[Any], columns: tuple[str, ...]) -> list[dict[str, Any]]:
    return [_record(row, columns) for row in rows]


def _hash_payload(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(
        dict(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _json_text(value: Mapping[str, object] | None, field_name: str) -> str:
    try:
        return encode_audit_metadata(value).text
    except PersistedJsonError as exc:
        raise PostgresMasterDataValidationError(f"{field_name} must be JSON-serializable.") from exc


def _outbox_json_text(value: Mapping[str, object]) -> str:
    try:
        return encode_postgres_outbox_payload(value).text
    except PersistedJsonError as exc:
        raise PostgresMasterDataValidationError("outbox payload must be JSON-serializable.") from exc


@dataclass(frozen=True)
class PostgresMasterDataRepository:
    """Persist tenant-scoped organization reference data in PostgreSQL.

    The connection is caller-owned and must already have ``app.tenant_id``
    set transaction-locally.  Tenant identifiers are also explicit query
    parameters so accidental unscoped repository calls fail closed at both the
    application and database layers.
    """

    connection: Any

    def _before_state_hash(
        self,
        *,
        table: str,
        parameters: tuple[Any, ...],
    ) -> str:
        try:
            query, columns = _BEFORE_STATE_HASH_QUERIES[table]
        except KeyError as exc:
            raise PostgresMasterDataError("Unsupported master-data reference table.") from exc
        cursor = self.connection.execute(query, parameters)
        row = cursor.fetchone()
        if row is None:
            return ""
        return _hash_payload(_record(row, columns))

    def _append_evidence(
        self,
        *,
        tenant_id: str,
        actor_id: str | None,
        request_id: str,
        action: str,
        resource_type: str,
        resource_id: str,
        before_state_hash: str,
        after_state: Mapping[str, object],
        metadata: Mapping[str, object] | None = None,
    ) -> None:
        if actor_id is None:
            return
        tenant = _tenant_id(tenant_id)
        actor = _required_text(actor_id, "actor_id")
        request = str(request_id or "").strip()
        if len(request) > 160:
            raise PostgresMasterDataValidationError("request_id must be at most 160 characters.")
        after_state_hash = _hash_payload(after_state)
        metadata_json = _json_text(metadata, "metadata")
        payload_json = _outbox_json_text(
            {
                "resource_type": resource_type,
                "resource_id": resource_id,
                "before_state_hash": before_state_hash,
                "after_state_hash": after_state_hash,
            }
        )
        self.connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (tenant,))
        audit_event_id = _hash_payload(
            {
                "tenant_id": tenant,
                "action": action,
                "resource_id": resource_id,
                "before_state_hash": before_state_hash,
                "after_state_hash": after_state_hash,
            }
        )
        previous_cursor = self.connection.execute(
            "SELECT event_hash FROM reconforge.audit_events WHERE tenant_id = %s ORDER BY event_sequence DESC LIMIT 1",
            (tenant,),
        )
        previous_row = previous_cursor.fetchone()
        previous_hash = "" if previous_row is None else str(previous_row[0] if not isinstance(previous_row, Mapping) else previous_row.get("event_hash") or "")
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
                "metadata": metadata_json,
            }
        )
        self.connection.execute(
            """
            INSERT INTO reconforge.audit_events
                (tenant_id, event_id, actor_id, action, resource_type, resource_id, occurred_at,
                 request_id, before_state_hash, after_state_hash, previous_event_hash, event_hash, reason, metadata)
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
                "",
                metadata_json,
            ),
        )
        outbox_event_id = _hash_payload(
            {
                "tenant_id": tenant,
                "event_type": f"master_data.{action}",
                "resource_type": resource_type,
                "resource_id": resource_id,
                "after_state_hash": after_state_hash,
            }
        )
        self.connection.execute(
            """
            INSERT INTO reconforge.outbox_events
                (tenant_id, event_id, event_type, aggregate_type, aggregate_id, payload)
            VALUES (%s, %s, %s, %s, %s, CAST(%s AS jsonb))
            ON CONFLICT (tenant_id, event_id) DO NOTHING
            """,
            (tenant, outbox_event_id, f"master_data.{action}", resource_type, resource_id, payload_json),
        )

    def upsert_currency(
        self,
        *,
        tenant_id: str,
        code: str,
        name: str,
        minor_units: int = 2,
        active: bool = True,
        actor_id: str | None = None,
        request_id: str = "",
        metadata: Mapping[str, object] | None = None,
    ) -> dict[str, Any]:
        tenant = _tenant_id(tenant_id)
        currency = _currency_code(code, "currency code")
        currency_name = _required_text(name, "currency name")
        if not 0 <= int(minor_units) <= 6:
            raise PostgresMasterDataValidationError("minor_units must be between 0 and 6.")
        before_state_hash = ""
        if actor_id is not None:
            before_state_hash = self._before_state_hash(
                table="currencies",
                parameters=(tenant, currency),
            )
        cursor = self.connection.execute(
            """
            INSERT INTO reconforge.currencies (tenant_id, code, name, minor_units, active)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id, code) DO UPDATE SET
                name = EXCLUDED.name,
                minor_units = EXCLUDED.minor_units,
                active = EXCLUDED.active,
                updated_at = now()
            RETURNING tenant_id, code, name, minor_units, active, created_at, updated_at
            """,
            (tenant, currency, currency_name, int(minor_units), bool(active)),
        )
        record = _record(
            cursor.fetchone(),
            ("tenant_id", "code", "name", "minor_units", "active", "created_at", "updated_at"),
        )
        self._append_evidence(
            tenant_id=tenant,
            actor_id=actor_id,
            request_id=request_id,
            action="currency_upserted",
            resource_type="currency",
            resource_id=currency,
            before_state_hash=before_state_hash,
            after_state=record,
            metadata=metadata,
        )
        return record

    def list_currencies(self, *, tenant_id: str, active_only: bool = False) -> list[dict[str, Any]]:
        tenant = _tenant_id(tenant_id)
        query = (
            "SELECT tenant_id, code, name, minor_units, active, created_at, updated_at "
            "FROM reconforge.currencies WHERE tenant_id = %s"
        )
        parameters: tuple[Any, ...] = (tenant,)
        if active_only:
            query += " AND active = TRUE"
        query += " ORDER BY code"
        cursor = self.connection.execute(query, parameters)
        return _records(
            cursor.fetchall(),
            ("tenant_id", "code", "name", "minor_units", "active", "created_at", "updated_at"),
        )

    def upsert_organization(
        self,
        *,
        tenant_id: str,
        organization_id: str,
        organization_code: str,
        name: str,
        base_currency: str | None = None,
        active: bool = True,
        actor_id: str | None = None,
        request_id: str = "",
        metadata: Mapping[str, object] | None = None,
    ) -> dict[str, Any]:
        tenant = _tenant_id(tenant_id)
        identifier = _scope_id(organization_id, "organization_id")
        code = _code(organization_code, "organization code")
        organization_name = _required_text(name, "organization name")
        currency = _currency_code(base_currency, "base currency") if base_currency is not None else None
        before_state_hash = ""
        if actor_id is not None:
            before_state_hash = self._before_state_hash(
                table="organizations",
                parameters=(tenant, identifier),
            )
        cursor = self.connection.execute(
            """
            INSERT INTO reconforge.organizations
                (tenant_id, id, organization_code, name, base_currency, active)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id, id) DO UPDATE SET
                organization_code = EXCLUDED.organization_code,
                name = EXCLUDED.name,
                base_currency = EXCLUDED.base_currency,
                active = EXCLUDED.active,
                updated_at = now()
            RETURNING tenant_id, id, organization_code, name, base_currency, active, created_at, updated_at
            """,
            (tenant, identifier, code, organization_name, currency, bool(active)),
        )
        record = _record(
            cursor.fetchone(),
            ("tenant_id", "id", "organization_code", "name", "base_currency", "active", "created_at", "updated_at"),
        )
        self._append_evidence(
            tenant_id=tenant,
            actor_id=actor_id,
            request_id=request_id,
            action="organization_upserted",
            resource_type="organization",
            resource_id=identifier,
            before_state_hash=before_state_hash,
            after_state=record,
            metadata=metadata,
        )
        return record

    def list_organizations(self, *, tenant_id: str, active_only: bool = False) -> list[dict[str, Any]]:
        tenant = _tenant_id(tenant_id)
        query = (
            "SELECT tenant_id, id, organization_code, name, base_currency, active, created_at, updated_at "
            "FROM reconforge.organizations WHERE tenant_id = %s"
        )
        parameters: tuple[Any, ...] = (tenant,)
        if active_only:
            query += " AND active = TRUE"
        query += " ORDER BY organization_code NULLS LAST, id"
        cursor = self.connection.execute(query, parameters)
        return _records(
            cursor.fetchall(),
            ("tenant_id", "id", "organization_code", "name", "base_currency", "active", "created_at", "updated_at"),
        )

    def upsert_legal_entity(
        self,
        *,
        tenant_id: str,
        organization_id: str,
        entity_id: str,
        entity_code: str,
        name: str,
        currency_code: str,
        active: bool = True,
        actor_id: str | None = None,
        request_id: str = "",
        metadata: Mapping[str, object] | None = None,
    ) -> dict[str, Any]:
        tenant = _tenant_id(tenant_id)
        organization = _scope_id(organization_id, "organization_id")
        identifier = _scope_id(entity_id, "legal_entity_id")
        code = _code(entity_code, "entity code")
        entity_name = _required_text(name, "entity name")
        currency = _currency_code(currency_code)
        before_state_hash = ""
        if actor_id is not None:
            before_state_hash = self._before_state_hash(
                table="legal_entities",
                parameters=(tenant, identifier),
            )
        cursor = self.connection.execute(
            """
            INSERT INTO reconforge.legal_entities
                (tenant_id, id, organization_id, entity_code, name, currency_code, active)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id, id) DO UPDATE SET
                organization_id = EXCLUDED.organization_id,
                entity_code = EXCLUDED.entity_code,
                name = EXCLUDED.name,
                currency_code = EXCLUDED.currency_code,
                active = EXCLUDED.active,
                updated_at = now()
            RETURNING tenant_id, id, organization_id, entity_code, name, currency_code, active, created_at, updated_at
            """,
            (tenant, identifier, organization, code, entity_name, currency, bool(active)),
        )
        record = _record(
            cursor.fetchone(),
            (
                "tenant_id",
                "id",
                "organization_id",
                "entity_code",
                "name",
                "currency_code",
                "active",
                "created_at",
                "updated_at",
            ),
        )
        self._append_evidence(
            tenant_id=tenant,
            actor_id=actor_id,
            request_id=request_id,
            action="legal_entity_upserted",
            resource_type="legal_entity",
            resource_id=identifier,
            before_state_hash=before_state_hash,
            after_state=record,
            metadata=metadata,
        )
        return record

    def list_legal_entities(self, *, tenant_id: str, organization_id: str | None = None) -> list[dict[str, Any]]:
        tenant = _tenant_id(tenant_id)
        organization = _optional_scope_id(organization_id, "organization_id")
        query = (
            "SELECT tenant_id, id, organization_id, entity_code, name, currency_code, active, created_at, updated_at "
            "FROM reconforge.legal_entities WHERE tenant_id = %s"
        )
        parameters: tuple[Any, ...] = (tenant,)
        if organization is not None:
            query += " AND organization_id = %s"
            parameters += (organization,)
        query += " ORDER BY organization_id, entity_code, id"
        cursor = self.connection.execute(query, parameters)
        return _records(
            cursor.fetchall(),
            (
                "tenant_id",
                "id",
                "organization_id",
                "entity_code",
                "name",
                "currency_code",
                "active",
                "created_at",
                "updated_at",
            ),
        )

    def upsert_branch(
        self,
        *,
        tenant_id: str,
        organization_id: str,
        branch_id: str,
        branch_code: str,
        name: str,
        legal_entity_id: str | None = None,
        active: bool = True,
        actor_id: str | None = None,
        request_id: str = "",
        metadata: Mapping[str, object] | None = None,
    ) -> dict[str, Any]:
        tenant = _tenant_id(tenant_id)
        organization = _scope_id(organization_id, "organization_id")
        identifier = _scope_id(branch_id, "branch_id")
        code = _code(branch_code, "branch code")
        branch_name = _required_text(name, "branch name")
        legal_entity = _optional_scope_id(legal_entity_id, "legal_entity_id")
        before_state_hash = ""
        if actor_id is not None:
            before_state_hash = self._before_state_hash(
                table="branches",
                parameters=(tenant, identifier),
            )
        cursor = self.connection.execute(
            """
            INSERT INTO reconforge.branches
                (tenant_id, id, organization_id, legal_entity_id, branch_code, name, active)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id, id) DO UPDATE SET
                organization_id = EXCLUDED.organization_id,
                legal_entity_id = EXCLUDED.legal_entity_id,
                branch_code = EXCLUDED.branch_code,
                name = EXCLUDED.name,
                active = EXCLUDED.active,
                updated_at = now()
            RETURNING tenant_id, id, organization_id, legal_entity_id, branch_code, name, active, created_at, updated_at
            """,
            (tenant, identifier, organization, legal_entity, code, branch_name, bool(active)),
        )
        record = _record(
            cursor.fetchone(),
            (
                "tenant_id",
                "id",
                "organization_id",
                "legal_entity_id",
                "branch_code",
                "name",
                "active",
                "created_at",
                "updated_at",
            ),
        )
        self._append_evidence(
            tenant_id=tenant,
            actor_id=actor_id,
            request_id=request_id,
            action="branch_upserted",
            resource_type="branch",
            resource_id=identifier,
            before_state_hash=before_state_hash,
            after_state=record,
            metadata=metadata,
        )
        return record

    def list_branches(self, *, tenant_id: str, organization_id: str | None = None) -> list[dict[str, Any]]:
        tenant = _tenant_id(tenant_id)
        organization = _optional_scope_id(organization_id, "organization_id")
        query = (
            "SELECT tenant_id, id, organization_id, legal_entity_id, branch_code, name, active, created_at, updated_at "
            "FROM reconforge.branches WHERE tenant_id = %s"
        )
        parameters: tuple[Any, ...] = (tenant,)
        if organization is not None:
            query += " AND organization_id = %s"
            parameters += (organization,)
        query += " ORDER BY organization_id, branch_code, id"
        cursor = self.connection.execute(query, parameters)
        return _records(
            cursor.fetchall(),
            (
                "tenant_id",
                "id",
                "organization_id",
                "legal_entity_id",
                "branch_code",
                "name",
                "active",
                "created_at",
                "updated_at",
            ),
        )

    def organization_by_code(self, *, tenant_id: str, organization_code: str) -> dict[str, Any]:
        """Resolve one organization code inside the current tenant scope."""

        tenant = _tenant_id(tenant_id)
        code = _code(organization_code, "organization code")
        cursor = self.connection.execute(
            """
            SELECT tenant_id, id, organization_code, name, base_currency, active, created_at, updated_at
            FROM reconforge.organizations
            WHERE tenant_id = %s AND organization_code = %s
            """,
            (tenant, code),
        )
        row = cursor.fetchone()
        if row is None:
            raise PostgresMasterDataError("Organization reference was not found.")
        return _record(
            row,
            ("tenant_id", "id", "organization_code", "name", "base_currency", "active", "created_at", "updated_at"),
        )

    def legal_entity_by_code(
        self,
        *,
        tenant_id: str,
        organization_id: str,
        entity_code: str,
    ) -> dict[str, Any]:
        """Resolve one legal entity without allowing cross-organization lookup."""

        tenant = _tenant_id(tenant_id)
        organization = _scope_id(organization_id, "organization_id")
        code = _code(entity_code, "entity code")
        cursor = self.connection.execute(
            """
            SELECT tenant_id, id, organization_id, entity_code, name, currency_code, active, created_at, updated_at
            FROM reconforge.legal_entities
            WHERE tenant_id = %s AND organization_id = %s AND entity_code = %s
            """,
            (tenant, organization, code),
        )
        row = cursor.fetchone()
        if row is None:
            raise PostgresMasterDataError("Legal-entity reference was not found.")
        return _record(
            row,
            (
                "tenant_id",
                "id",
                "organization_id",
                "entity_code",
                "name",
                "currency_code",
                "active",
                "created_at",
                "updated_at",
            ),
        )

    def upsert_period(
        self,
        *,
        tenant_id: str,
        period_id: str,
        name: str,
        start_date: str,
        end_date: str,
        fiscal_year: int | None = None,
        period_number: int | None = None,
        actor_id: str | None = None,
        request_id: str = "",
        metadata: Mapping[str, object] | None = None,
    ) -> dict[str, Any]:
        """Create or update non-overlapping tenant fiscal-period metadata."""

        tenant = _tenant_id(tenant_id)
        identifier = _scope_id(period_id, "period_id")
        period_name = _required_text(name, "period name")
        start = _iso_date(start_date, "period start date")
        end = _iso_date(end_date, "period end date")
        if end < start:
            raise PostgresMasterDataValidationError("Period end date must be on or after the start date.")
        year = int(fiscal_year) if fiscal_year is not None else int(start[:4])
        number = int(period_number) if period_number is not None else int(start[5:7])
        if not 1900 <= year <= 9999:
            raise PostgresMasterDataValidationError("Fiscal year must be between 1900 and 9999.")
        if not 1 <= number <= 999:
            raise PostgresMasterDataValidationError("Period number must be between 1 and 999.")

        # Serialize period mutations per tenant so the overlap check and write
        # remain safe under concurrent API requests without requiring an
        # extension-backed exclusion constraint.
        self.connection.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (tenant,))
        name_cursor = self.connection.execute(
            "SELECT id FROM reconforge.fiscal_periods WHERE tenant_id = %s AND name = %s",
            (tenant, period_name),
        )
        name_row = name_cursor.fetchone()
        if name_row is not None:
            identifier = _scope_id(str(name_row[0] if not isinstance(name_row, Mapping) else name_row.get("id")), "period_id")
        before_state_hash = ""
        if actor_id is not None:
            before_state_hash = self._before_state_hash(
                table="fiscal_periods",
                parameters=(tenant, identifier),
            )
        overlap_cursor = self.connection.execute(
            """
            SELECT id FROM reconforge.fiscal_periods
            WHERE tenant_id = %s AND id <> %s AND start_date <= %s AND end_date >= %s
            LIMIT 1
            """,
            (tenant, identifier, end, start),
        )
        if overlap_cursor.fetchone() is not None:
            raise PostgresMasterDataValidationError("Fiscal periods in the same tenant must not overlap.")
        cursor = self.connection.execute(
            """
            INSERT INTO reconforge.fiscal_periods
                (tenant_id, id, name, start_date, end_date, status, fiscal_year, period_number, status_reason)
            VALUES (%s, %s, %s, %s, %s, 'Open', %s, %s, '')
            ON CONFLICT (tenant_id, id) DO UPDATE SET
                name = EXCLUDED.name,
                start_date = EXCLUDED.start_date,
                end_date = EXCLUDED.end_date,
                fiscal_year = EXCLUDED.fiscal_year,
                period_number = EXCLUDED.period_number,
                updated_at = now()
            RETURNING tenant_id, id, name, start_date, end_date, status, created_at,
                      fiscal_year, period_number, status_reason, updated_at
            """,
            (tenant, identifier, period_name, start, end, year, number),
        )
        record = _record(
            cursor.fetchone(),
            (
                "tenant_id",
                "id",
                "name",
                "start_date",
                "end_date",
                "status",
                "created_at",
                "fiscal_year",
                "period_number",
                "status_reason",
                "updated_at",
            ),
        )
        self._append_evidence(
            tenant_id=tenant,
            actor_id=actor_id,
            request_id=request_id,
            action="fiscal_period_upserted",
            resource_type="fiscal_period",
            resource_id=identifier,
            before_state_hash=before_state_hash,
            after_state=record,
            metadata=metadata,
        )
        return record

    def list_periods(self, *, tenant_id: str) -> list[dict[str, Any]]:
        """List tenant fiscal periods in deterministic calendar order."""

        tenant = _tenant_id(tenant_id)
        cursor = self.connection.execute(
            """
            SELECT tenant_id, id, name, start_date, end_date, status, created_at,
                   fiscal_year, period_number, status_reason, updated_at
            FROM reconforge.fiscal_periods
            WHERE tenant_id = %s
            ORDER BY start_date, period_number, id
            """,
            (tenant,),
        )
        return _records(
            cursor.fetchall(),
            (
                "tenant_id",
                "id",
                "name",
                "start_date",
                "end_date",
                "status",
                "created_at",
                "fiscal_year",
                "period_number",
                "status_reason",
                "updated_at",
            ),
        )

    def set_period_status(
        self,
        *,
        tenant_id: str,
        period_id: str,
        status: str,
        reason: str = "",
        actor_id: str | None = None,
        request_id: str = "",
        metadata: Mapping[str, object] | None = None,
    ) -> dict[str, Any]:
        """Apply the bounded fiscal-period metadata state machine."""

        tenant = _tenant_id(tenant_id)
        identifier = _scope_id(period_id, "period_id")
        target = _period_status(status)
        clean_reason = _period_reason(reason)
        cursor = self.connection.execute(
            """
            SELECT tenant_id, id, name, start_date, end_date, status, created_at,
                   fiscal_year, period_number, status_reason, updated_at
            FROM reconforge.fiscal_periods
            WHERE tenant_id = %s AND id = %s
            FOR UPDATE
            """,
            (tenant, identifier),
        )
        row = cursor.fetchone()
        if row is None:
            raise PostgresMasterDataError("Fiscal-period reference was not found.")
        current_record = _record(
            row,
            (
                "tenant_id",
                "id",
                "name",
                "start_date",
                "end_date",
                "status",
                "created_at",
                "fiscal_year",
                "period_number",
                "status_reason",
                "updated_at",
            ),
        )
        current = str(current_record["status"])
        if target == current:
            return current_record
        if target not in _PERIOD_TRANSITIONS.get(current, set()):
            raise PostgresMasterDataValidationError("Invalid fiscal-period status transition.")
        if target == "Open" and not clean_reason:
            raise PostgresMasterDataValidationError("Reopening a fiscal period requires a reason.")
        before_state_hash = ""
        if actor_id is not None:
            before_state_hash = _hash_payload(current_record)
        self.connection.execute(
            """
            UPDATE reconforge.fiscal_periods
            SET status = %s, status_reason = %s, updated_at = now()
            WHERE tenant_id = %s AND id = %s AND status = %s
            """,
            (target, clean_reason, tenant, identifier, current),
        )
        updated_cursor = self.connection.execute(
            """
            SELECT tenant_id, id, name, start_date, end_date, status, created_at,
                   fiscal_year, period_number, status_reason, updated_at
            FROM reconforge.fiscal_periods
            WHERE tenant_id = %s AND id = %s
            """,
            (tenant, identifier),
        )
        updated = _record(
            updated_cursor.fetchone(),
            (
                "tenant_id",
                "id",
                "name",
                "start_date",
                "end_date",
                "status",
                "created_at",
                "fiscal_year",
                "period_number",
                "status_reason",
                "updated_at",
            ),
        )
        self._append_evidence(
            tenant_id=tenant,
            actor_id=actor_id,
            request_id=request_id,
            action="fiscal_period_status_changed",
            resource_type="fiscal_period",
            resource_id=identifier,
            before_state_hash=before_state_hash,
            after_state=updated,
            metadata={**dict(metadata or {}), "from_status": current, "to_status": target, "reason": clean_reason},
        )
        return updated

    def summary(self, *, tenant_id: str) -> dict[str, Any]:
        """Return counts for the PostgreSQL master-data bounded context."""

        tenant = _tenant_id(tenant_id)
        cursor = self.connection.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM reconforge.organizations WHERE tenant_id = %s) AS organizations,
                (SELECT COUNT(*) FROM reconforge.legal_entities WHERE tenant_id = %s) AS legal_entities,
                (SELECT COUNT(*) FROM reconforge.branches WHERE tenant_id = %s) AS branches,
                (SELECT COUNT(*) FROM reconforge.currencies WHERE tenant_id = %s AND active = TRUE) AS active_currencies,
                (SELECT COUNT(*) FROM reconforge.fiscal_periods WHERE tenant_id = %s) AS periods
            """,
            (tenant, tenant, tenant, tenant, tenant),
        )
        row = cursor.fetchone()
        if row is None:
            raise PostgresMasterDataError("PostgreSQL master-data summary returned no record.")
        values = row if not isinstance(row, Mapping) else None
        return {
            "schema_version": 1,
            "source": {"kind": "postgres-master-data", "server_mode": True, "external_calls": False},
            "tenant_id": tenant,
            "organizations": int(row[0] if values is not None else row.get("organizations") or 0),
            "legal_entities": int(row[1] if values is not None else row.get("legal_entities") or 0),
            "branches": int(row[2] if values is not None else row.get("branches") or 0),
            "periods": int(row[4] if values is not None else row.get("periods") or 0),
            "active_currencies": int(row[3] if values is not None else row.get("active_currencies") or 0),
            "unsupported_collections": [],
        }


POSTGRES_MASTER_DATA_SCHEMA_SQL = """
ALTER TABLE reconforge.organizations
    ADD COLUMN IF NOT EXISTS organization_code TEXT,
    ADD COLUMN IF NOT EXISTS base_currency TEXT,
    ADD COLUMN IF NOT EXISTS active BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

CREATE UNIQUE INDEX IF NOT EXISTS idx_organizations_tenant_code
    ON reconforge.organizations (tenant_id, organization_code)
    WHERE organization_code IS NOT NULL;

CREATE TABLE IF NOT EXISTS reconforge.currencies (
    tenant_id TEXT NOT NULL,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    minor_units INTEGER NOT NULL DEFAULT 2 CHECK (minor_units BETWEEN 0 AND 6),
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, code),
    FOREIGN KEY (tenant_id) REFERENCES reconforge.tenants(id) ON DELETE CASCADE,
    CHECK (code ~ '^[A-Z]{3}$')
);

DO $reconforge$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE connamespace = 'reconforge'::regnamespace
          AND conrelid = 'reconforge.organizations'::regclass
          AND conname = 'organizations_tenant_base_currency_fk'
    ) THEN
        ALTER TABLE reconforge.organizations
            ADD CONSTRAINT organizations_tenant_base_currency_fk
            FOREIGN KEY (tenant_id, base_currency)
            REFERENCES reconforge.currencies(tenant_id, code)
            ON DELETE RESTRICT;
    END IF;
END
$reconforge$;

CREATE TABLE IF NOT EXISTS reconforge.legal_entities (
    tenant_id TEXT NOT NULL,
    id TEXT NOT NULL,
    organization_id TEXT NOT NULL,
    entity_code TEXT NOT NULL,
    name TEXT NOT NULL,
    currency_code TEXT NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, organization_id, entity_code),
    FOREIGN KEY (tenant_id, organization_id)
        REFERENCES reconforge.organizations(tenant_id, id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id, currency_code)
        REFERENCES reconforge.currencies(tenant_id, code) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS reconforge.branches (
    tenant_id TEXT NOT NULL,
    id TEXT NOT NULL,
    organization_id TEXT NOT NULL,
    legal_entity_id TEXT,
    branch_code TEXT NOT NULL,
    name TEXT NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, organization_id, branch_code),
    FOREIGN KEY (tenant_id, organization_id)
        REFERENCES reconforge.organizations(tenant_id, id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id, legal_entity_id)
        REFERENCES reconforge.legal_entities(tenant_id, id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_currencies_tenant_active
    ON reconforge.currencies (tenant_id, active, code);
CREATE INDEX IF NOT EXISTS idx_legal_entities_tenant_org
    ON reconforge.legal_entities (tenant_id, organization_id, active, entity_code);
CREATE INDEX IF NOT EXISTS idx_branches_tenant_org
    ON reconforge.branches (tenant_id, organization_id, active, branch_code);

ALTER TABLE reconforge.currencies ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.currencies FORCE ROW LEVEL SECURITY;
ALTER TABLE reconforge.legal_entities ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.legal_entities FORCE ROW LEVEL SECURITY;
ALTER TABLE reconforge.branches ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.branches FORCE ROW LEVEL SECURITY;

DO $reconforge$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'reconforge' AND tablename = 'currencies' AND policyname = 'tenant_scope'
    ) THEN
        CREATE POLICY tenant_scope ON reconforge.currencies
            USING (tenant_id = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'reconforge' AND tablename = 'legal_entities' AND policyname = 'tenant_scope'
    ) THEN
        CREATE POLICY tenant_scope ON reconforge.legal_entities
            USING (tenant_id = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'reconforge' AND tablename = 'branches' AND policyname = 'tenant_scope'
    ) THEN
        CREATE POLICY tenant_scope ON reconforge.branches
            USING (tenant_id = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
    END IF;
END
$reconforge$;
"""


POSTGRES_FISCAL_PERIOD_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS reconforge.fiscal_periods (
    tenant_id TEXT NOT NULL,
    id TEXT NOT NULL,
    name TEXT NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    status TEXT NOT NULL DEFAULT 'Open' CHECK (status IN ('Open', 'Soft Closed', 'Closed')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    fiscal_year INTEGER NOT NULL CHECK (fiscal_year BETWEEN 1900 AND 9999),
    period_number INTEGER NOT NULL CHECK (period_number BETWEEN 1 AND 999),
    status_reason TEXT NOT NULL DEFAULT '',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, name),
    CHECK (end_date >= start_date),
    FOREIGN KEY (tenant_id) REFERENCES reconforge.tenants(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_fiscal_periods_tenant_calendar
    ON reconforge.fiscal_periods (tenant_id, start_date, period_number, id);

ALTER TABLE reconforge.fiscal_periods ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.fiscal_periods FORCE ROW LEVEL SECURITY;

DO $reconforge$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'reconforge' AND tablename = 'fiscal_periods' AND policyname = 'tenant_scope'
    ) THEN
        CREATE POLICY tenant_scope ON reconforge.fiscal_periods
            USING (tenant_id = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
    END IF;
END
$reconforge$;
"""
