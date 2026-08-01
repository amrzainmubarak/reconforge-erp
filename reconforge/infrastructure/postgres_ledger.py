"""Tenant-scoped PostgreSQL ledger-control repository.

The repository is intentionally independent from the local SQLite
``FinanceCoreService``.  It provides a small server-side financial boundary:
account references, balanced journal entries, append-only posted records, and
transactional audit/outbox evidence.  Callers own the transaction and must
establish a transaction-local tenant scope with ``PostgresTenantBoundary``.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from reconforge.infrastructure.postgres import PostgresConfigurationError, normalize_scope_id, validate_tenant_id
from reconforge.io.persisted import (
    PersistedJsonError,
    decode_audit_metadata,
    encode_audit_metadata,
    encode_postgres_outbox_payload,
)
from reconforge.utils.time import utc_now_text

_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_CODE_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9._/-]{0,63}$")
_CURRENCY_PATTERN = re.compile(r"^[A-Z]{3}$")
_DECIMAL_PATTERN = re.compile(r"^(0|[0-9]+)(\.[0-9]+)?$")
_MAX_INTEGER_DIGITS = 20
_MAX_SCALE = 18
_ACCOUNT_TYPES = ("Asset", "Liability", "Equity", "Income", "Expense", "Off Balance")
_NORMAL_BALANCES = ("Debit", "Credit")
_SOURCE_TYPES = ("Manual", "Imported", "Generated")


class PostgresLedgerValidationError(ValueError):
    """Raised when a ledger input is invalid before SQL execution."""


class PostgresLedgerIntegrityError(RuntimeError):
    """Raised when a ledger write conflicts with an existing immutable record."""


class PostgresLedgerNotFoundError(PostgresLedgerIntegrityError):
    """Raised when a requested tenant-scoped ledger record does not exist."""


@dataclass(frozen=True)
class LedgerLine:
    """One debit or credit line in a balanced entry."""

    account_id: str
    debit: object
    credit: object
    description: str = ""
    reference: str = ""


def _text(value: object, field_name: str, *, maximum: int = 255) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise PostgresLedgerValidationError(f"{field_name} must not be blank.")
    if any(ord(character) < 32 or ord(character) == 127 for character in normalized):
        raise PostgresLedgerValidationError(f"{field_name} must contain printable characters only.")
    if len(normalized) > maximum:
        raise PostgresLedgerValidationError(f"{field_name} must be at most {maximum} characters.")
    return " ".join(normalized.split())


def _optional_text(value: object, field_name: str, *, maximum: int = 255) -> str:
    if value is None or not str(value).strip():
        return ""
    return _text(value, field_name, maximum=maximum)


def _scope_id(value: str, field_name: str) -> str:
    try:
        normalized = normalize_scope_id(value, field_name=field_name)
    except PostgresConfigurationError as exc:
        raise PostgresLedgerValidationError(str(exc)) from exc
    if not _ID_PATTERN.fullmatch(normalized):
        raise PostgresLedgerValidationError(f"{field_name} has an invalid identifier.")
    return normalized


def _tenant_id(value: str) -> str:
    try:
        return validate_tenant_id(value)
    except PostgresConfigurationError as exc:
        raise PostgresLedgerValidationError(str(exc)) from exc


def _code(value: object, field_name: str) -> str:
    normalized = _text(value, field_name, maximum=64).upper()
    if not _CODE_PATTERN.fullmatch(normalized):
        raise PostgresLedgerValidationError(
            f"{field_name} must use 1-64 uppercase letters, numbers, dots, underscores, hyphens, or slashes."
        )
    return normalized


def _currency(value: object, field_name: str = "currency_code") -> str:
    normalized = _text(value, field_name, maximum=3).upper()
    if not _CURRENCY_PATTERN.fullmatch(normalized):
        raise PostgresLedgerValidationError(f"{field_name} must be a three-letter ISO-style code.")
    return normalized


def _choice(value: object, field_name: str, choices: tuple[str, ...]) -> str:
    normalized = _text(value, field_name, maximum=40).casefold()
    for choice in choices:
        if choice.casefold() == normalized:
            return choice
    raise PostgresLedgerValidationError(f"{field_name} must be one of: {', '.join(choices)}.")


def _posting_date(value: object) -> str:
    raw = _text(value, "posting_date", maximum=10)
    try:
        parsed = date.fromisoformat(raw)
    except ValueError as exc:
        raise PostgresLedgerValidationError("posting_date must use YYYY-MM-DD format.") from exc
    if parsed.isoformat() != raw:
        raise PostgresLedgerValidationError("posting_date must use YYYY-MM-DD format.")
    return raw


def _amount(value: object, field_name: str) -> tuple[Decimal, str]:
    if value is None or isinstance(value, (bool, float)):
        raise PostgresLedgerValidationError(f"{field_name} must be an exact non-negative decimal.")
    raw = str(value).strip()
    if not raw or len(raw) > 64 or not _DECIMAL_PATTERN.fullmatch(raw):
        raise PostgresLedgerValidationError(f"{field_name} must be an exact non-negative decimal.")
    try:
        parsed = Decimal(raw)
    except InvalidOperation as exc:
        raise PostgresLedgerValidationError(f"{field_name} must be an exact non-negative decimal.") from exc
    if not parsed.is_finite() or parsed < 0:
        raise PostgresLedgerValidationError(f"{field_name} must be an exact non-negative decimal.")
    decimal_tuple = parsed.as_tuple()
    digits = decimal_tuple.digits
    exponent = decimal_tuple.exponent
    if not isinstance(exponent, int):
        raise PostgresLedgerValidationError(f"{field_name} must be an exact non-negative decimal.")
    scale = max(0, -exponent)
    integer_digits = max(1, len(digits) + exponent) if exponent >= 0 else max(1, len(digits) - scale)
    if scale > _MAX_SCALE or integer_digits > _MAX_INTEGER_DIGITS:
        raise PostgresLedgerValidationError(
            f"{field_name} exceeds NUMERIC(38,18) precision (maximum {_MAX_INTEGER_DIGITS} integer digits and {_MAX_SCALE} decimals)."
        )
    canonical = format(parsed, "f")
    if "." in canonical:
        canonical = canonical.rstrip("0").rstrip(".")
    return parsed, canonical or "0"


def _minor_amount(value: object, minor_units: int, field_name: str) -> int:
    try:
        amount = Decimal(str(value or "0"))
    except InvalidOperation as exc:
        raise PostgresLedgerValidationError(f"{field_name} is not an exact numeric amount.") from exc
    if not amount.is_finite():
        raise PostgresLedgerValidationError(f"{field_name} is not an exact numeric amount.")
    scaled = amount * (Decimal(10) ** minor_units)
    if scaled != scaled.to_integral_value():
        raise PostgresLedgerValidationError(f"{field_name} exceeds the currency's {minor_units}-decimal precision.")
    return int(scaled)


def _minor_text(value: int, minor_units: int) -> str:
    amount = Decimal(value).scaleb(-minor_units)
    return f"{amount:.{minor_units}f}"


def _json_text(value: Mapping[str, object] | None, field_name: str) -> str:
    try:
        return encode_audit_metadata(value).text
    except PersistedJsonError as exc:
        raise PostgresLedgerValidationError(f"{field_name} must be JSON-serializable.") from exc


def _outbox_json_text(value: Mapping[str, object]) -> str:
    try:
        return encode_postgres_outbox_payload(value).text
    except PersistedJsonError as exc:
        raise PostgresLedgerValidationError("outbox payload must be JSON-serializable.") from exc


def _row_value(row: Any, key: str, index: int) -> Any:
    if isinstance(row, Mapping):
        return row.get(key)
    return row[index]


def _record(row: Any, columns: tuple[str, ...]) -> dict[str, Any]:
    if row is None:
        raise PostgresLedgerIntegrityError("PostgreSQL ledger operation returned no record.")
    if isinstance(row, Mapping):
        return {str(key): value for key, value in row.items()}
    values = tuple(row)
    if len(values) != len(columns):
        raise PostgresLedgerIntegrityError("PostgreSQL ledger record shape was unexpected.")
    return dict(zip(columns, values, strict=True))


def _hash_payload(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(dict(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class PostgresLedgerRepository:
    """Write and read tenant-scoped, balanced PostgreSQL ledger entries.

    No method commits or rolls back.  The caller must own the transaction and
    establish ``app.tenant_id`` before calling a method.  Database constraints
    and deferred triggers remain authoritative for balance and immutability.
    """

    connection: Any

    _ACCOUNT_COLUMNS = (
        "tenant_id",
        "id",
        "organization_id",
        "account_code",
        "name",
        "account_type",
        "normal_balance",
        "active",
        "created_at",
        "updated_at",
    )
    _ENTRY_COLUMNS = (
        "tenant_id",
        "id",
        "entry_number",
        "organization_id",
        "currency_code",
        "posting_date",
        "description",
        "status",
        "source_type",
        "source_id",
        "entry_fingerprint",
        "created_at",
        "posted_at",
    )

    _ORGANIZATION_COLUMNS = ("tenant_id", "id", "organization_code", "base_currency", "active")

    _ACCOUNT_LOOKUP_COLUMNS = ("tenant_id", "id", "organization_id", "account_code", "active")

    def upsert_account(
        self,
        *,
        tenant_id: str,
        organization_id: str,
        account_id: str,
        account_code: str,
        name: str,
        account_type: str = "Asset",
        normal_balance: str = "Debit",
        active: bool = True,
        actor_id: str | None = None,
        request_id: str = "",
        reason: str = "",
        metadata: Mapping[str, object] | None = None,
    ) -> dict[str, Any]:
        tenant = _tenant_id(tenant_id)
        organization = _scope_id(organization_id, "organization_id")
        identifier = _scope_id(account_id, "account_id")
        code = _code(account_code, "account_code")
        account_name = _text(name, "account name")
        selected_type = _choice(account_type, "account_type", _ACCOUNT_TYPES)
        selected_balance = _choice(normal_balance, "normal_balance", _NORMAL_BALANCES)
        before_cursor = self.connection.execute(
            """
            SELECT tenant_id, id, organization_id, account_code, name, account_type,
                   normal_balance, active, created_at, updated_at
            FROM reconforge.ledger_accounts
            WHERE tenant_id = %s AND id = %s
            """,
            (tenant, identifier),
        )
        before_row = before_cursor.fetchone()
        before_state_hash = "" if before_row is None else _hash_payload(_record(before_row, self._ACCOUNT_COLUMNS))
        cursor = self.connection.execute(
            """
            INSERT INTO reconforge.ledger_accounts
                (tenant_id, id, organization_id, account_code, name, account_type, normal_balance, active)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id, id) DO UPDATE SET
                organization_id = EXCLUDED.organization_id,
                account_code = EXCLUDED.account_code,
                name = EXCLUDED.name,
                account_type = EXCLUDED.account_type,
                normal_balance = EXCLUDED.normal_balance,
                active = EXCLUDED.active,
                updated_at = now()
            RETURNING tenant_id, id, organization_id, account_code, name, account_type,
                      normal_balance, active, created_at, updated_at
            """,
            (tenant, identifier, organization, code, account_name, selected_type, selected_balance, bool(active)),
        )
        record = _record(cursor.fetchone(), self._ACCOUNT_COLUMNS)
        if actor_id is None:
            return record

        actor = _text(actor_id, "actor_id", maximum=160)
        request = _optional_text(request_id, "request_id", maximum=160)
        audit_reason = _optional_text(reason, "reason", maximum=500)
        metadata_json = _json_text(metadata, "metadata")
        after_state_hash = _hash_payload(record)
        outbox_payload_json = _outbox_json_text(
            {
                "account_id": identifier,
                "account_code": code,
                "organization_id": organization,
                "after_state_hash": after_state_hash,
            }
        )
        self.connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (tenant,))
        audit_event_id = _hash_payload(
            {
                "tenant_id": tenant,
                "action": "ledger_account_upserted",
                "resource_id": identifier,
                "after_state_hash": after_state_hash,
            }
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
                "action": "ledger_account_upserted",
                "resource_type": "ledger_account",
                "resource_id": identifier,
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
                 request_id, before_state_hash, after_state_hash, previous_event_hash, event_hash, reason, metadata)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CAST(%s AS jsonb))
            ON CONFLICT (tenant_id, event_id) DO NOTHING
            """,
            (
                tenant,
                audit_event_id,
                actor,
                "ledger_account_upserted",
                "ledger_account",
                identifier,
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
        outbox_event_id = _hash_payload(
            {
                "tenant_id": tenant,
                "event_type": "ledger.account_upserted",
                "resource_id": identifier,
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
            (
                tenant,
                outbox_event_id,
                "ledger.account_upserted",
                "ledger_account",
                identifier,
                outbox_payload_json,
            ),
        )
        return record

    def list_accounts(self, *, tenant_id: str, organization_id: str | None = None) -> list[dict[str, Any]]:
        tenant = _tenant_id(tenant_id)
        organization = (
            None
            if organization_id is None or not str(organization_id).strip()
            else _scope_id(organization_id, "organization_id")
        )
        query = (
            "SELECT tenant_id, id, organization_id, account_code, name, account_type, normal_balance, active, "
            "created_at, updated_at FROM reconforge.ledger_accounts WHERE tenant_id = %s"
        )
        parameters: tuple[Any, ...] = (tenant,)
        if organization is not None:
            query += " AND organization_id = %s"
            parameters += (organization,)
        query += " ORDER BY organization_id, account_code, id"
        cursor = self.connection.execute(query, parameters)
        rows = cursor.fetchall()
        return [_record(row, self._ACCOUNT_COLUMNS) for row in rows]

    def organization_by_code(self, *, tenant_id: str, organization_code: str) -> dict[str, Any]:
        """Resolve one tenant-scoped organization reference for API adapters."""

        tenant = _tenant_id(tenant_id)
        code = _code(organization_code, "organization_code")
        cursor = self.connection.execute(
            """
            SELECT tenant_id, id, organization_code, base_currency, active
            FROM reconforge.organizations
            WHERE tenant_id = %s AND organization_code = %s
            """,
            (tenant, code),
        )
        row = cursor.fetchone()
        if row is None:
            raise PostgresLedgerIntegrityError("The organization reference was not found.")
        return _record(row, self._ORGANIZATION_COLUMNS)

    def account_by_code(
        self,
        *,
        tenant_id: str,
        organization_id: str,
        account_code: str,
    ) -> dict[str, Any]:
        """Resolve one posting account without allowing cross-organization lookup."""

        tenant = _tenant_id(tenant_id)
        organization = _scope_id(organization_id, "organization_id")
        code = _code(account_code, "account_code")
        cursor = self.connection.execute(
            """
            SELECT tenant_id, id, organization_id, account_code, active
            FROM reconforge.ledger_accounts
            WHERE tenant_id = %s AND organization_id = %s AND account_code = %s
            """,
            (tenant, organization, code),
        )
        row = cursor.fetchone()
        if row is None:
            raise PostgresLedgerIntegrityError("The posting account reference was not found.")
        return _record(row, self._ACCOUNT_LOOKUP_COLUMNS)

    def post_entry(
        self,
        *,
        tenant_id: str,
        entry_id: str,
        entry_number: str,
        organization_id: str,
        currency_code: str,
        posting_date: object,
        description: str,
        lines: Sequence[LedgerLine],
        actor_id: str,
        request_id: str = "",
        source_type: str = "Manual",
        source_id: str | None = None,
        reason: str = "",
        metadata: Mapping[str, object] | None = None,
    ) -> dict[str, Any]:
        tenant = _tenant_id(tenant_id)
        identifier = _scope_id(entry_id, "entry_id")
        number = _code(entry_number, "entry_number")
        organization = _scope_id(organization_id, "organization_id")
        currency = _currency(currency_code)
        posting = _posting_date(posting_date)
        entry_description = _text(description, "entry description")
        actor = _text(actor_id, "actor_id", maximum=160)
        request = _optional_text(request_id, "request_id", maximum=160)
        selected_source = _choice(source_type, "source_type", _SOURCE_TYPES)
        source = _optional_text(source_id, "source_id", maximum=160)
        audit_reason = _optional_text(reason, "reason", maximum=500)
        metadata_json = _json_text(metadata, "metadata")
        normalized_lines = tuple(lines)
        if len(normalized_lines) < 2:
            raise PostgresLedgerValidationError("A posted ledger entry requires at least two lines.")
        debit_total = Decimal("0")
        credit_total = Decimal("0")
        line_values: list[tuple[int, str, str, str, str, str]] = []
        fingerprint_lines: list[dict[str, str | int]] = []
        for line_number, line in enumerate(normalized_lines, start=1):
            if not isinstance(line, LedgerLine):
                raise PostgresLedgerValidationError("lines must contain only LedgerLine values.")
            account = _scope_id(line.account_id, f"lines[{line_number}].account_id")
            debit, debit_text = _amount(line.debit, f"lines[{line_number}].debit")
            credit, credit_text = _amount(line.credit, f"lines[{line_number}].credit")
            if (debit == 0) == (credit == 0):
                raise PostgresLedgerValidationError(
                    f"lines[{line_number}] must contain exactly one positive debit or credit amount."
                )
            debit_total += debit
            credit_total += credit
            description_text = _optional_text(line.description, f"lines[{line_number}].description")
            reference_text = _optional_text(line.reference, f"lines[{line_number}].reference")
            line_values.append((line_number, account, description_text, reference_text, debit_text, credit_text))
            fingerprint_lines.append(
                {
                    "line_number": line_number,
                    "account_id": account,
                    "debit": debit_text,
                    "credit": credit_text,
                    "description": description_text,
                    "reference": reference_text,
                }
            )
        if debit_total != credit_total:
            raise PostgresLedgerValidationError(
                f"Ledger entry is unbalanced: debit {debit_total} does not equal credit {credit_total}."
            )
        payload_json = _outbox_json_text(
            {
                "entry_id": identifier,
                "entry_number": number,
                "organization_id": organization,
                "currency_code": currency,
                "debit_total": str(debit_total),
                "credit_total": str(credit_total),
                "line_count": len(line_values),
            }
        )
        fingerprint = _hash_payload(
            {
                "tenant_id": tenant,
                "entry_id": identifier,
                "entry_number": number,
                "organization_id": organization,
                "currency_code": currency,
                "posting_date": posting,
                "description": entry_description,
                "source_type": selected_source,
                "source_id": source,
                "lines": fingerprint_lines,
            }
        )

        # Serialize the tenant's audit chain inside the caller's transaction.
        self.connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (tenant,))
        existing_cursor = self.connection.execute(
            "SELECT entry_fingerprint, status FROM reconforge.ledger_entries WHERE tenant_id = %s AND id = %s",
            (tenant, identifier),
        )
        existing = existing_cursor.fetchone()
        if existing is not None:
            existing_fingerprint = _row_value(existing, "entry_fingerprint", 0)
            if str(existing_fingerprint) != fingerprint:
                raise PostgresLedgerIntegrityError("A ledger entry identifier already exists with different content.")
            if str(_row_value(existing, "status", 1)) != "Posted":
                raise PostgresLedgerIntegrityError("A matching ledger entry is not posted and cannot be reused.")
            return self.get_entry(tenant_id=tenant, entry_id=identifier)

        self.connection.execute(
            """
            INSERT INTO reconforge.ledger_entries
                (tenant_id, id, entry_number, organization_id, currency_code, posting_date,
                 description, status, source_type, source_id, entry_fingerprint)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'Draft', %s, %s, %s)
            """,
            (
                tenant,
                identifier,
                number,
                organization,
                currency,
                posting,
                entry_description,
                selected_source,
                source,
                fingerprint,
            ),
        )
        for line_number, account, line_description, reference, debit_text, credit_text in line_values:
            self.connection.execute(
                """
                INSERT INTO reconforge.ledger_lines
                    (tenant_id, entry_id, line_number, account_id, description, reference, debit_amount, credit_amount)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (tenant, identifier, line_number, account, line_description, reference, debit_text, credit_text),
            )
        posted_cursor = self.connection.execute(
            """
            UPDATE reconforge.ledger_entries
            SET status = 'Posted', posted_at = now()
            WHERE tenant_id = %s AND id = %s AND status = 'Draft'
            RETURNING tenant_id, id, entry_number, organization_id, currency_code, posting_date,
                      description, status, source_type, source_id, entry_fingerprint, created_at, posted_at
            """,
            (tenant, identifier),
        )
        posted = posted_cursor.fetchone()
        if posted is None:
            raise PostgresLedgerIntegrityError("Ledger entry could not be posted.")
        entry = _record(posted, self._ENTRY_COLUMNS)
        current_hash = _hash_payload(
            {
                "entry": entry,
                "lines": fingerprint_lines,
            }
        )
        audit_event_id = _hash_payload(
            {"tenant_id": tenant, "action": "ledger_entry_posted", "resource_id": identifier}
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
                "action": "ledger_entry_posted",
                "resource_type": "ledger_entry",
                "resource_id": identifier,
                "occurred_at": occurred_at,
                "request_id": request,
                "before_state_hash": "",
                "after_state_hash": current_hash,
                "previous_event_hash": previous_hash,
                "reason": audit_reason,
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
                "ledger_entry_posted",
                "ledger_entry",
                identifier,
                occurred_at,
                request,
                "",
                current_hash,
                previous_hash,
                event_hash,
                audit_reason,
                metadata_json,
            ),
        )
        outbox_event_id = _hash_payload(
            {"tenant_id": tenant, "event_type": "ledger.entry_posted", "resource_id": identifier}
        )
        self.connection.execute(
            """
            INSERT INTO reconforge.outbox_events
                (tenant_id, event_id, event_type, aggregate_type, aggregate_id, payload)
            VALUES (%s, %s, %s, %s, %s, CAST(%s AS jsonb))
            ON CONFLICT (tenant_id, event_id) DO NOTHING
            """,
            (tenant, outbox_event_id, "ledger.entry_posted", "ledger_entry", identifier, payload_json),
        )
        return self.get_entry(tenant_id=tenant, entry_id=identifier)

    def get_entry(self, *, tenant_id: str, entry_id: str) -> dict[str, Any]:
        tenant = _tenant_id(tenant_id)
        identifier = _scope_id(entry_id, "entry_id")
        entry_cursor = self.connection.execute(
            """
            SELECT tenant_id, id, entry_number, organization_id, currency_code, posting_date,
                   description, status, source_type, source_id, entry_fingerprint, created_at, posted_at
            FROM reconforge.ledger_entries
            WHERE tenant_id = %s AND id = %s
            """,
            (tenant, identifier),
        )
        entry_row = entry_cursor.fetchone()
        if entry_row is None:
            raise PostgresLedgerNotFoundError("Ledger entry was not found.")
        line_cursor = self.connection.execute(
            """
            SELECT tenant_id, entry_id, line_number, account_id, description, reference, debit_amount, credit_amount
            FROM reconforge.ledger_lines
            WHERE tenant_id = %s AND entry_id = %s
            ORDER BY line_number
            """,
            (tenant, identifier),
        )
        entry = _record(entry_row, self._ENTRY_COLUMNS)
        entry["lines"] = [
            _record(
                row,
                (
                    "tenant_id",
                    "entry_id",
                    "line_number",
                    "account_id",
                    "description",
                    "reference",
                    "debit_amount",
                    "credit_amount",
                ),
            )
            for row in line_cursor.fetchall()
        ]
        return entry

    def list_entries(
        self,
        *,
        tenant_id: str,
        organization_id: str | None = None,
        status: str | None = None,
        limit: int = 500,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List the bounded server ledger entries with deterministic ordering."""

        tenant = _tenant_id(tenant_id)
        if not 1 <= int(limit) <= 100_000:
            raise PostgresLedgerValidationError("limit must be between 1 and 100000.")
        if not 0 <= int(offset) <= 10_000_000:
            raise PostgresLedgerValidationError("offset must be between 0 and 10000000.")
        organization = (
            None
            if organization_id is None or not str(organization_id).strip()
            else _scope_id(organization_id, "organization_id")
        )
        query = """
            SELECT entries.tenant_id, entries.id, entries.entry_number, entries.organization_id,
                   entries.currency_code, entries.posting_date, entries.description, entries.status,
                   entries.source_type, entries.source_id, entries.entry_fingerprint, entries.created_at,
                   entries.posted_at, COUNT(lines.line_number) AS line_count,
                   COALESCE(SUM(lines.debit_amount), 0) AS debit_total,
                   COALESCE(SUM(lines.credit_amount), 0) AS credit_total
            FROM reconforge.ledger_entries AS entries
            LEFT JOIN reconforge.ledger_lines AS lines
              ON lines.tenant_id = entries.tenant_id AND lines.entry_id = entries.id
            WHERE entries.tenant_id = %s
        """
        parameters: list[Any] = [tenant]
        if organization is not None:
            query += " AND entries.organization_id = %s"
            parameters.append(organization)
        if status:
            selected_status = _choice(status, "status", ("Draft", "Posted"))
            query += " AND entries.status = %s"
            parameters.append(selected_status)
        query += """
            GROUP BY entries.tenant_id, entries.id, entries.entry_number, entries.organization_id,
                     entries.currency_code, entries.posting_date, entries.description, entries.status,
                     entries.source_type, entries.source_id, entries.entry_fingerprint,
                     entries.created_at, entries.posted_at
            ORDER BY entries.posting_date DESC, entries.entry_number, entries.id
            LIMIT %s OFFSET %s
        """
        parameters.extend((int(limit), int(offset)))
        cursor = self.connection.execute(query, tuple(parameters))
        columns = self._ENTRY_COLUMNS + ("line_count", "debit_total", "credit_total")
        return [_record(row, columns) for row in cursor.fetchall()]

    def trial_balance(
        self,
        *,
        tenant_id: str,
        organization_id: str,
        organization_code: str,
        period_id: str,
    ) -> dict[str, Any]:
        """Aggregate immutable posted entries for one tenant organization and period."""

        tenant = _tenant_id(tenant_id)
        organization = _scope_id(organization_id, "organization_id")
        code = _code(organization_code, "organization_code")
        period = _scope_id(period_id, "period_id")
        period_cursor = self.connection.execute(
            """
            SELECT id, name, start_date, end_date
            FROM reconforge.fiscal_periods
            WHERE tenant_id = %s AND id = %s
            """,
            (tenant, period),
        )
        period_row = period_cursor.fetchone()
        if period_row is None:
            raise PostgresLedgerNotFoundError("Fiscal period was not found.")
        period_record = _record(period_row, ("id", "name", "start_date", "end_date"))
        currency_cursor = self.connection.execute(
            """
            SELECT DISTINCT entries.currency_code
            FROM reconforge.ledger_entries AS entries
            WHERE entries.tenant_id = %s
              AND entries.organization_id = %s
              AND entries.status = 'Posted'
              AND entries.posting_date BETWEEN %s AND %s
            ORDER BY entries.currency_code
            """,
            (tenant, organization, period_record["start_date"], period_record["end_date"]),
        )
        currencies = currency_cursor.fetchall()
        currency_codes = [str(_row_value(row, "currency_code", 0)) for row in currencies]
        if len(currency_codes) > 1:
            raise PostgresLedgerValidationError(
                "Trial balance requires one currency per organization and fiscal period."
            )
        if currency_codes:
            currency_code = _currency(currency_codes[0])
        else:
            base_currency_cursor = self.connection.execute(
                """
                SELECT currencies.code
                FROM reconforge.organizations AS organizations
                JOIN reconforge.currencies AS currencies
                  ON currencies.tenant_id = organizations.tenant_id
                 AND currencies.code = organizations.base_currency
                WHERE organizations.tenant_id = %s AND organizations.id = %s
                """,
                (tenant, organization),
            )
            base_currency_row = base_currency_cursor.fetchone()
            if base_currency_row is None:
                raise PostgresLedgerValidationError("A base currency is required to produce an empty trial balance.")
            currency_code = _currency(_row_value(base_currency_row, "code", 0))
        minor_cursor = self.connection.execute(
            "SELECT minor_units FROM reconforge.currencies WHERE tenant_id = %s AND code = %s",
            (tenant, currency_code),
        )
        minor_row = minor_cursor.fetchone()
        if minor_row is None:
            raise PostgresLedgerNotFoundError("Trial-balance currency was not found.")
        minor_units = int(_row_value(minor_row, "minor_units", 0))
        rows_cursor = self.connection.execute(
            """
            SELECT accounts.account_code, accounts.name AS account_name, accounts.account_type,
                   accounts.normal_balance, SUM(lines.debit_amount) AS debit_amount,
                   SUM(lines.credit_amount) AS credit_amount
            FROM reconforge.ledger_entries AS entries
            JOIN reconforge.ledger_lines AS lines
              ON lines.tenant_id = entries.tenant_id AND lines.entry_id = entries.id
            JOIN reconforge.ledger_accounts AS accounts
              ON accounts.tenant_id = lines.tenant_id AND accounts.id = lines.account_id
            WHERE entries.tenant_id = %s
              AND entries.organization_id = %s
              AND entries.currency_code = %s
              AND entries.status = 'Posted'
              AND entries.posting_date BETWEEN %s AND %s
            GROUP BY accounts.id, accounts.account_code, accounts.name,
                     accounts.account_type, accounts.normal_balance
            ORDER BY accounts.account_code
            """,
            (
                tenant,
                organization,
                currency_code,
                period_record["start_date"],
                period_record["end_date"],
            ),
        )
        accounts: list[dict[str, object]] = []
        total_debit = 0
        total_credit = 0
        for row in rows_cursor.fetchall():
            debit_minor = _minor_amount(_row_value(row, "debit_amount", 4), minor_units, "debit total")
            credit_minor = _minor_amount(_row_value(row, "credit_amount", 5), minor_units, "credit total")
            total_debit += debit_minor
            total_credit += credit_minor
            balance_minor = debit_minor - credit_minor
            accounts.append(
                {
                    "account_code": _row_value(row, "account_code", 0),
                    "account_name": _row_value(row, "account_name", 1),
                    "account_type": _row_value(row, "account_type", 2),
                    "normal_balance": _row_value(row, "normal_balance", 3),
                    "debit_minor": debit_minor,
                    "credit_minor": credit_minor,
                    "balance_minor": balance_minor,
                    "debit": _minor_text(debit_minor, minor_units),
                    "credit": _minor_text(credit_minor, minor_units),
                    "balance": _minor_text(balance_minor, minor_units),
                }
            )
        return {
            "schema_version": 1,
            "source": {"kind": "postgres-ledger-control", "server_mode": True, "external_calls": False},
            "workspace": None,
            "organization_code": code,
            "entity_code": "",
            "period_id": period_record["id"],
            "period_name": period_record["name"],
            "currency_code": currency_code,
            "currency_minor_units": minor_units,
            "totals": {
                "debit_minor": total_debit,
                "credit_minor": total_credit,
                "balanced": total_debit == total_credit,
                "debit": _minor_text(total_debit, minor_units),
                "credit": _minor_text(total_credit, minor_units),
            },
            "accounts": accounts,
        }

    def list_audit_events(self, *, tenant_id: str, limit: int | None = None) -> list[dict[str, Any]]:
        """List tenant-scoped PostgreSQL audit events in chain order."""

        tenant = _tenant_id(tenant_id)
        if limit is not None and not 1 <= int(limit) <= 100_000:
            raise PostgresLedgerValidationError("limit must be between 1 and 100000.")
        query = """
            SELECT event_sequence, tenant_id, event_id, actor_id, action, resource_type, resource_id,
                   occurred_at::text AS occurred_at_text, request_id, before_state_hash,
                   after_state_hash, previous_event_hash, event_hash, reason, metadata::text AS metadata_text
            FROM reconforge.audit_events
            WHERE tenant_id = %s
            ORDER BY event_sequence
        """
        parameters: list[Any] = [tenant]
        if limit is not None:
            query += " LIMIT %s"
            parameters.append(int(limit))
        cursor = self.connection.execute(query, tuple(parameters))
        columns = (
            "event_sequence",
            "tenant_id",
            "event_id",
            "actor_id",
            "action",
            "resource_type",
            "resource_id",
            "occurred_at_text",
            "request_id",
            "before_state_hash",
            "after_state_hash",
            "previous_event_hash",
            "event_hash",
            "reason",
            "metadata_text",
        )
        events: list[dict[str, Any]] = []
        for row in cursor.fetchall():
            record = _record(row, columns)
            metadata_text = str(record.pop("metadata_text") or "{}")
            try:
                record["metadata"] = decode_audit_metadata(metadata_text).payload
            except PersistedJsonError as exc:
                raise PostgresLedgerIntegrityError("Stored PostgreSQL audit metadata is invalid.") from exc
            record["occurred_at"] = record.pop("occurred_at_text")
            events.append(record)
        return events

    def verify_audit_events(self, *, tenant_id: str) -> dict[str, Any]:
        """Verify tenant-scoped PostgreSQL audit links and event hashes."""

        tenant = _tenant_id(tenant_id)
        cursor = self.connection.execute(
            """
            SELECT event_sequence, tenant_id, event_id, actor_id, action, resource_type, resource_id,
                   to_char(occurred_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS occurred_at_text,
                   request_id, before_state_hash, after_state_hash, previous_event_hash,
                   event_hash, reason, metadata::text AS metadata_text
            FROM reconforge.audit_events
            WHERE tenant_id = %s
            ORDER BY event_sequence
            """,
            (tenant,),
        )
        columns = (
            "event_sequence",
            "tenant_id",
            "event_id",
            "actor_id",
            "action",
            "resource_type",
            "resource_id",
            "occurred_at_text",
            "request_id",
            "before_state_hash",
            "after_state_hash",
            "previous_event_hash",
            "event_hash",
            "reason",
            "metadata_text",
        )
        issues: list[dict[str, object]] = []
        expected_previous_hash = ""
        checked_events = 0
        for row in cursor.fetchall():
            record = _record(row, columns)
            checked_events += 1
            sequence = int(record["event_sequence"])
            actual_previous_hash = str(record["previous_event_hash"] or "")
            if actual_previous_hash != expected_previous_hash:
                issues.append(
                    {
                        "sequence": sequence,
                        "message": "Audit event previous hash does not match the tenant chain head.",
                    }
                )
            metadata_text = str(record["metadata_text"] or "{}")
            try:
                metadata_json = encode_audit_metadata(decode_audit_metadata(metadata_text).payload).text
            except PersistedJsonError:
                issues.append({"sequence": sequence, "message": "Audit event metadata is invalid."})
                metadata_json = metadata_text
            expected_hash = _hash_payload(
                {
                    "tenant_id": str(record["tenant_id"]),
                    "event_id": str(record["event_id"]),
                    "actor_id": str(record["actor_id"]),
                    "action": str(record["action"]),
                    "resource_type": str(record["resource_type"]),
                    "resource_id": str(record["resource_id"]),
                    "occurred_at": str(record["occurred_at_text"]),
                    "request_id": str(record["request_id"] or ""),
                    "before_state_hash": str(record["before_state_hash"] or ""),
                    "after_state_hash": str(record["after_state_hash"] or ""),
                    "previous_event_hash": actual_previous_hash,
                    "reason": str(record["reason"] or ""),
                    "metadata": metadata_json,
                }
            )
            actual_hash = str(record["event_hash"])
            if actual_hash != expected_hash:
                issues.append({"sequence": sequence, "message": "Audit event hash does not match row content."})
            expected_previous_hash = actual_hash
        return {
            "ok": not issues,
            "checked_events": checked_events,
            "head_hash": expected_previous_hash,
            "issues": issues,
        }

    def summary(self, *, tenant_id: str) -> dict[str, Any]:
        """Return counts for the PostgreSQL ledger-control bounded context."""

        tenant = _tenant_id(tenant_id)
        cursor = self.connection.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM reconforge.ledger_accounts WHERE tenant_id = %s) AS accounts,
                (SELECT COUNT(*) FROM reconforge.ledger_entries WHERE tenant_id = %s AND status = 'Draft') AS drafts,
                (SELECT COUNT(*) FROM reconforge.ledger_entries WHERE tenant_id = %s AND status = 'Posted') AS posted
            """,
            (tenant, tenant, tenant),
        )
        row = cursor.fetchone()
        if row is None:
            raise PostgresLedgerIntegrityError("PostgreSQL ledger summary returned no record.")
        return {
            "schema_version": 1,
            "source": {"kind": "postgres-ledger-control", "server_mode": True, "external_calls": False},
            "tenant_id": tenant,
            "accounts": int(_row_value(row, "accounts", 0) or 0),
            "draft_entries": int(_row_value(row, "drafts", 1) or 0),
            "posted_entries": int(_row_value(row, "posted", 2) or 0),
            "unsupported_collections": ["charts", "dimensions", "dimension_values", "journals"],
        }


POSTGRES_LEDGER_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS reconforge.ledger_accounts (
    tenant_id TEXT NOT NULL,
    id TEXT NOT NULL,
    organization_id TEXT NOT NULL,
    account_code TEXT NOT NULL,
    name TEXT NOT NULL,
    account_type TEXT NOT NULL,
    normal_balance TEXT NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, organization_id, account_code),
    FOREIGN KEY (tenant_id, organization_id)
        REFERENCES reconforge.organizations(tenant_id, id) ON DELETE RESTRICT,
    CHECK (account_type IN ('Asset', 'Liability', 'Equity', 'Income', 'Expense', 'Off Balance')),
    CHECK (normal_balance IN ('Debit', 'Credit'))
);

CREATE TABLE IF NOT EXISTS reconforge.ledger_entries (
    tenant_id TEXT NOT NULL,
    id TEXT NOT NULL,
    entry_number TEXT NOT NULL,
    organization_id TEXT NOT NULL,
    currency_code TEXT NOT NULL,
    posting_date DATE NOT NULL,
    description TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Draft',
    source_type TEXT NOT NULL DEFAULT 'Manual',
    source_id TEXT,
    entry_fingerprint TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    posted_at TIMESTAMPTZ,
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, entry_number),
    FOREIGN KEY (tenant_id, organization_id)
        REFERENCES reconforge.organizations(tenant_id, id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id, currency_code)
        REFERENCES reconforge.currencies(tenant_id, code) ON DELETE RESTRICT,
    CHECK (status IN ('Draft', 'Posted')),
    CHECK (source_type IN ('Manual', 'Imported', 'Generated'))
);

CREATE TABLE IF NOT EXISTS reconforge.ledger_lines (
    tenant_id TEXT NOT NULL,
    entry_id TEXT NOT NULL,
    line_number INTEGER NOT NULL CHECK (line_number > 0),
    account_id TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    reference TEXT NOT NULL DEFAULT '',
    debit_amount NUMERIC(38,18) NOT NULL DEFAULT 0 CHECK (debit_amount >= 0),
    credit_amount NUMERIC(38,18) NOT NULL DEFAULT 0 CHECK (credit_amount >= 0),
    PRIMARY KEY (tenant_id, entry_id, line_number),
    FOREIGN KEY (tenant_id, entry_id)
        REFERENCES reconforge.ledger_entries(tenant_id, id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id, account_id)
        REFERENCES reconforge.ledger_accounts(tenant_id, id) ON DELETE RESTRICT,
    CHECK ((debit_amount > 0 AND credit_amount = 0) OR (credit_amount > 0 AND debit_amount = 0))
);

CREATE TABLE IF NOT EXISTS reconforge.audit_events (
    event_sequence BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE,
    tenant_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    action TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    request_id TEXT NOT NULL DEFAULT '',
    before_state_hash TEXT NOT NULL DEFAULT '',
    after_state_hash TEXT NOT NULL DEFAULT '',
    previous_event_hash TEXT NOT NULL DEFAULT '',
    event_hash TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (tenant_id, event_id),
    FOREIGN KEY (tenant_id) REFERENCES reconforge.tenants(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS reconforge.outbox_events (
    tenant_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    aggregate_type TEXT NOT NULL,
    aggregate_id TEXT NOT NULL,
    payload JSONB NOT NULL,
    status TEXT NOT NULL DEFAULT 'Pending',
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    available_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    claimed_at TIMESTAMPTZ,
    claimed_by TEXT,
    published_at TIMESTAMPTZ,
    last_error TEXT,
    dead_lettered_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, event_id),
    FOREIGN KEY (tenant_id) REFERENCES reconforge.tenants(id) ON DELETE CASCADE,
    CHECK (status IN ('Pending', 'Claimed', 'Published', 'Dead'))
);

CREATE INDEX IF NOT EXISTS idx_ledger_accounts_tenant_org_code
    ON reconforge.ledger_accounts (tenant_id, organization_id, account_code);
CREATE INDEX IF NOT EXISTS idx_ledger_entries_tenant_date
    ON reconforge.ledger_entries (tenant_id, posting_date, entry_number);
CREATE INDEX IF NOT EXISTS idx_ledger_lines_tenant_account
    ON reconforge.ledger_lines (tenant_id, account_id, entry_id);
CREATE INDEX IF NOT EXISTS idx_audit_events_tenant_sequence
    ON reconforge.audit_events (tenant_id, event_sequence);
CREATE INDEX IF NOT EXISTS idx_outbox_events_pending
    ON reconforge.outbox_events (tenant_id, status, available_at, created_at);
CREATE INDEX IF NOT EXISTS idx_outbox_events_claimed
    ON reconforge.outbox_events (tenant_id, claimed_by, claimed_at);

CREATE OR REPLACE FUNCTION reconforge.assert_ledger_entry_balanced()
RETURNS trigger
LANGUAGE plpgsql
AS $reconforge$
DECLARE
    line_count BIGINT;
    debit_total NUMERIC(38,18);
    credit_total NUMERIC(38,18);
BEGIN
    IF NEW.status <> 'Posted' THEN
        RETURN NEW;
    END IF;
    SELECT COUNT(*), COALESCE(SUM(debit_amount), 0), COALESCE(SUM(credit_amount), 0)
      INTO line_count, debit_total, credit_total
      FROM reconforge.ledger_lines
     WHERE tenant_id = NEW.tenant_id AND entry_id = NEW.id;
    IF line_count < 2 THEN
        RAISE EXCEPTION 'Posted ledger entry must contain at least two lines' USING ERRCODE = '23514';
    END IF;
    IF debit_total <> credit_total THEN
        RAISE EXCEPTION 'Posted ledger entry is not balanced' USING ERRCODE = '23514';
    END IF;
    IF EXISTS (
        SELECT 1
          FROM reconforge.ledger_lines lines
          JOIN reconforge.ledger_accounts accounts
            ON accounts.tenant_id = lines.tenant_id AND accounts.id = lines.account_id
         WHERE lines.tenant_id = NEW.tenant_id
           AND lines.entry_id = NEW.id
           AND accounts.organization_id <> NEW.organization_id
    ) THEN
        RAISE EXCEPTION 'Ledger line account belongs to another organization' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$reconforge$;

CREATE OR REPLACE FUNCTION reconforge.reject_posted_ledger_entry_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $reconforge$
BEGIN
    IF pg_trigger_depth() > 1 THEN
        IF TG_OP = 'DELETE' THEN
            RETURN OLD;
        END IF;
        RETURN NEW;
    END IF;
    IF OLD.status = 'Posted' THEN
        RAISE EXCEPTION 'Posted ledger entries are immutable' USING ERRCODE = '55000';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END
$reconforge$;

CREATE OR REPLACE FUNCTION reconforge.reject_posted_ledger_line_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $reconforge$
DECLARE
    entry_status TEXT;
    target_entry_id TEXT;
BEGIN
    IF pg_trigger_depth() > 1 THEN
        IF TG_OP = 'DELETE' THEN
            RETURN OLD;
        END IF;
        RETURN NEW;
    END IF;
    target_entry_id := CASE WHEN TG_OP = 'DELETE' THEN OLD.entry_id ELSE NEW.entry_id END;
    SELECT status INTO entry_status
      FROM reconforge.ledger_entries
     WHERE tenant_id = CASE WHEN TG_OP = 'DELETE' THEN OLD.tenant_id ELSE NEW.tenant_id END
       AND id = target_entry_id;
    IF entry_status = 'Posted' THEN
        RAISE EXCEPTION 'Posted ledger lines are immutable' USING ERRCODE = '55000';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END
$reconforge$;

CREATE OR REPLACE FUNCTION reconforge.reject_audit_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $reconforge$
BEGIN
    IF pg_trigger_depth() > 1 THEN
        RETURN OLD;
    END IF;
    RAISE EXCEPTION 'Audit events are append-only' USING ERRCODE = '55000';
END
$reconforge$;

DO $reconforge$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'ledger_entries_balanced') THEN
        CREATE CONSTRAINT TRIGGER ledger_entries_balanced
        AFTER INSERT OR UPDATE OF status ON reconforge.ledger_entries
        DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
        EXECUTE FUNCTION reconforge.assert_ledger_entry_balanced();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'ledger_entries_immutable') THEN
        CREATE TRIGGER ledger_entries_immutable
        BEFORE UPDATE OR DELETE ON reconforge.ledger_entries
        FOR EACH ROW EXECUTE FUNCTION reconforge.reject_posted_ledger_entry_mutation();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'ledger_lines_immutable') THEN
        CREATE TRIGGER ledger_lines_immutable
        BEFORE INSERT OR UPDATE OR DELETE ON reconforge.ledger_lines
        FOR EACH ROW EXECUTE FUNCTION reconforge.reject_posted_ledger_line_mutation();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'audit_events_append_only') THEN
        CREATE TRIGGER audit_events_append_only
        BEFORE UPDATE OR DELETE ON reconforge.audit_events
        FOR EACH ROW EXECUTE FUNCTION reconforge.reject_audit_mutation();
    END IF;
END
$reconforge$;

ALTER TABLE reconforge.ledger_accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.ledger_accounts FORCE ROW LEVEL SECURITY;
ALTER TABLE reconforge.ledger_entries ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.ledger_entries FORCE ROW LEVEL SECURITY;
ALTER TABLE reconforge.ledger_lines ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.ledger_lines FORCE ROW LEVEL SECURITY;
ALTER TABLE reconforge.audit_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.audit_events FORCE ROW LEVEL SECURITY;
ALTER TABLE reconforge.outbox_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.outbox_events FORCE ROW LEVEL SECURITY;

DO $reconforge$
DECLARE
    table_name TEXT;
BEGIN
    FOREACH table_name IN ARRAY ARRAY['ledger_accounts', 'ledger_entries', 'ledger_lines', 'audit_events', 'outbox_events']
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
