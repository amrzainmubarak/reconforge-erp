"""Shared helpers for local DB-backed finance workflows."""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import Any

from reconforge.audit import AuditLedgerError, append_audit_event
from reconforge.auth import AuthRepositoryError, AuthServiceError, LocalAuthService
from reconforge.auth.models import LocalUser
from reconforge.auth.policy import CentralPolicyEngine, PolicyEvaluationContext, audit_policy_decision
from reconforge.db.connection import DatabaseError
from reconforge.db.exporter import resolve_input_file
from reconforge.domain.models import DEFAULT_LOCAL_FIRST_NOTE, AuditEventReference, utc_now_text
from reconforge.io.records import (
    BusinessRecordDocument,
    RecordIngressError,
    read_business_record_document,
)
from reconforge.utils.money import InvalidAmountError, parse_amount
from reconforge.utils.time import utc_today


class PlatformError(ValueError):
    """Raised for safe, user-facing platform workflow errors."""


_TRUSTED_LOCAL_MODE: ContextVar[bool] = ContextVar("reconforge_trusted_local_mode", default=True)


@dataclass(frozen=True)
class ServerPrincipal:
    """A verified server identity snapshot propagated through one request."""

    user: LocalUser
    permissions: frozenset[str]


_SERVER_PRINCIPAL: ContextVar[ServerPrincipal | None] = ContextVar("reconforge_server_principal", default=None)


def is_trusted_local_mode() -> bool:
    """Return whether the current execution context may use an unbound local actor."""

    return _TRUSTED_LOCAL_MODE.get()


@contextmanager
def trusted_local_mode(enabled: bool) -> Iterator[None]:
    """Scope trusted-local actor compatibility to an explicit execution context.

    CLI and local service callers retain compatibility by default. Server request
    handlers must set this to ``False`` so every mutation has a bound principal.
    """

    token = _TRUSTED_LOCAL_MODE.set(enabled)
    try:
        yield
    finally:
        _TRUSTED_LOCAL_MODE.reset(token)


def current_server_principal() -> ServerPrincipal | None:
    """Return the verified server principal bound to the current request, if any."""

    return _SERVER_PRINCIPAL.get()


@contextmanager
def server_principal_context(principal: ServerPrincipal) -> Iterator[None]:
    """Bind one verified server principal until the request dependency exits."""

    previous = _SERVER_PRINCIPAL.get()
    _SERVER_PRINCIPAL.set(principal)
    try:
        yield
    finally:
        # FastAPI may resume a synchronous generator dependency in a different
        # worker context during teardown; restoring the value avoids reusing a
        # token created in another context while still clearing the principal.
        _SERVER_PRINCIPAL.set(previous)


REQUIRED_PLATFORM_TABLES = {
    "account_reconciliation_records",
    "close_periods",
    "approval_requests",
    "evidence_registry",
    "exceptions_queue",
    "metric_snapshots",
    "currencies",
    "branches",
}


def ensure_platform_schema(connection: sqlite3.Connection) -> None:
    """Ensure the finance platform migration has been applied."""

    try:
        existing = {
            str(row["name"])
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        }
    except sqlite3.DatabaseError as exc:
        raise DatabaseError("Unable to read ReconForge database. Run 'reconforge db migrate' first.") from exc
    if not existing >= REQUIRED_PLATFORM_TABLES:
        raise DatabaseError("ReconForge finance workflow schema is not initialized. Run 'reconforge db migrate' first.")
    ensure_outbox_schema(connection)


def ensure_outbox_schema(connection: sqlite3.Connection) -> None:
    """Ensure the local transactional outbox exists without changing caller transactions.

    Migration 13 is the canonical schema definition. The compatibility guard remains
    additive for legacy databases at version 12 that are opened before an explicit
    migration command; running migrations records the versioned change.
    """

    had_transaction = connection.in_transaction
    try:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS outbox_events (
                id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                aggregate_type TEXT NOT NULL,
                aggregate_id TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                published_at TEXT,
                attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
                last_error TEXT
            )
            """,
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_outbox_events_pending
            ON outbox_events(published_at, created_at, id)
            """,
        )
        if not had_transaction:
            connection.commit()
    except sqlite3.DatabaseError as exc:
        if not had_transaction:
            connection.rollback()
        raise DatabaseError("Unable to initialize the local transactional outbox.") from exc


def append_outbox_event(
    connection: sqlite3.Connection,
    *,
    event_id: str,
    event_type: str,
    aggregate_type: str,
    aggregate_id: str,
    payload: dict[str, Any],
) -> str:
    """Append an outbox event inside the caller's current transaction."""

    try:
        payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    except (TypeError, ValueError) as exc:
        raise PlatformError("Outbox event payload must be JSON-serializable.") from exc
    try:
        connection.execute(
            """
            INSERT OR IGNORE INTO outbox_events (
                id, event_type, aggregate_type, aggregate_id, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                normalize_key(event_id, default=""),
                normalize_key(event_type, default=""),
                normalize_key(aggregate_type, default=""),
                normalize_key(aggregate_id, default=""),
                payload_json,
                utc_now_text(),
            ),
        )
    except sqlite3.DatabaseError as exc:
        raise PlatformError("Unable to append the transactional outbox event.") from exc
    return event_id


def platform_id(prefix: str, *parts: object) -> str:
    """Create a deterministic local identifier for idempotent DB workflows."""

    payload = "|".join(str(part).strip() for part in parts)
    return f"{prefix}-{sha256(payload.encode('utf-8')).hexdigest()[:16]}"


def normalize_text(value: object, *, default: str = "") -> str:
    """Normalize user-provided scalar text without raising tracebacks."""

    if value is None:
        return default
    cleaned = str(value).strip()
    return cleaned if cleaned else default


def normalize_key(value: object, *, default: str = "local") -> str:
    """Return a stable non-empty key value."""

    return normalize_text(value, default=default).replace("\n", " ")[:160]


def to_float(value: object, *, default: float | None = None) -> float:
    """Parse a local numeric value safely without silent coercion.

    Invalid inputs raise ``PlatformError`` unless a caller explicitly provides
    ``default``.

    .. note::
        Do NOT use ``to_float`` for financial calculations, monetary balances,
        reconciliation matching tolerances, or accounting postings. Use
        ``parse_amount()`` or ``Decimal`` types instead.
    """

    try:
        parsed = parse_amount(value)
    except InvalidAmountError as exc:
        if default is None:
            raise PlatformError("Invalid local float value.") from exc
        return default
    return float(parsed)


def to_int(value: object, *, default: int | None = None) -> int:
    """Parse a local integer value safely without silent coercion.

    Invalid inputs (including fractional values) raise ``PlatformError`` unless a
    caller explicitly provides ``default``.
    """

    try:
        parsed = parse_amount(value)
    except InvalidAmountError as exc:
        if default is None:
            raise PlatformError("Invalid local integer value.") from exc
        return default
    if parsed != parsed.to_integral_value():
        if default is None:
            raise PlatformError("Local integer value must not contain fractional digits.")
        return default
    try:
        return int(parsed)
    except (OverflowError, ValueError) as exc:
        if default is None:
            raise PlatformError("Local integer value is out of range.") from exc
        return default


def parse_financial_amount(
    value: object,
    *,
    field: str | None = None,
    decimal_separator: str | None = None,
    thousands_separator: str | None = None,
) -> Decimal:
    """Parse a user-facing financial amount into :class:`Decimal`.

    The parser is strict on invalid values and does not silently coerce errors
    to zero. The optional ``field`` argument is included for backward
    compatibility with existing validation messages throughout the platform.
    """

    try:
        return parse_amount(value, decimal_separator=decimal_separator, thousands_separator=thousands_separator)
    except InvalidAmountError as exc:
        if field:
            raise PlatformError(f"Could not parse financial amount for field '{field}'.") from exc
        raise PlatformError("Could not parse financial amount.") from exc


def to_bool(value: object) -> bool:
    """Parse common CSV/JSON truthy values."""

    return normalize_text(value).lower() in {"1", "true", "yes", "y", "manual"}


def parse_date(value: object) -> date | None:
    """Parse ISO-like local dates."""

    text = normalize_text(value)
    if not text:
        return None
    for candidate in (text, text[:10]):
        try:
            return date.fromisoformat(candidate)
        except ValueError:
            continue
    return None


def age_days(created_at: str) -> int:
    """Return whole days from a stored UTC timestamp/date to now."""

    parsed = parse_date(created_at)
    if parsed is None:
        return 0
    return max((utc_today() - parsed).days, 0)


def date_diff_days(left: object, right: object) -> int | None:
    """Return absolute day difference, or ``None`` when either date is invalid."""

    left_date = parse_date(left)
    right_date = parse_date(right)
    if left_date is None or right_date is None:
        return None
    return abs((left_date - right_date).days)


def read_local_record_document(input_path: Path | str) -> BusinessRecordDocument:
    """Read bounded local CSV/JSON records with parsed-byte provenance."""

    resolved = resolve_input_file(input_path)
    if resolved.suffix.lower() not in {".csv", ".json"}:
        raise PlatformError("Input file must be CSV or JSON.")
    try:
        return read_business_record_document(resolved)
    except RecordIngressError as exc:
        raise PlatformError("Unable to read local input records.") from exc


def read_local_records(input_path: Path | str) -> tuple[Path, list[dict[str, Any]]]:
    """Compatibility shim returning the bounded local record path and rows."""

    document = read_local_record_document(input_path)
    return document.source_path, document.records


def ensure_workspace(connection: sqlite3.Connection, workspace: str = "default") -> str:
    """Create or return a local workspace reference."""

    ensure_platform_schema(connection)
    owns_transaction = not connection.in_transaction
    name = normalize_key(workspace, default="default")
    workspace_id = platform_id("WS", name)
    now = utc_now_text()
    try:
        connection.execute(
            """
            INSERT OR IGNORE INTO workspaces (id, name, local_first_note, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (workspace_id, name, DEFAULT_LOCAL_FIRST_NOTE, now),
        )
        inventory_schema = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'units_of_measure'"
        ).fetchone()
        if inventory_schema is not None:
            connection.execute(
                """
                INSERT OR IGNORE INTO units_of_measure (
                    id, workspace_id, uom_code, name, category, decimal_places,
                    active, created_at, updated_at
                ) VALUES (?, ?, 'EA', 'Each', 'Count', 0, 1, ?, ?)
                """,
                (f"UOM-{workspace_id}", workspace_id, now, now),
            )
        if owns_transaction:
            connection.commit()
    except sqlite3.DatabaseError as exc:
        if owns_transaction:
            connection.rollback()
        raise PlatformError("Unable to prepare local workspace reference.") from exc
    return workspace_id


def ensure_account(connection: sqlite3.Connection, *, workspace_id: str, account_code: str, account_name: str) -> str:
    """Create or return a local account reference."""

    owns_transaction = not connection.in_transaction
    code = normalize_key(account_code, default="UNKNOWN")
    name = normalize_text(account_name, default=code)
    account_id = platform_id("ACC", workspace_id, code)
    now = utc_now_text()
    try:
        account_columns = {str(row["name"]) for row in connection.execute("PRAGMA table_info(accounts)").fetchall()}
        if "chart_id" in account_columns:
            chart_id = f"COA-{workspace_id}"
            connection.execute(
                """
                INSERT OR IGNORE INTO charts_of_accounts (
                    id, workspace_id, organization_id, chart_code, name, description,
                    active, created_at, updated_at
                ) VALUES (?, ?, NULL, 'DEFAULT', 'Default chart of accounts',
                          'Shared local chart for compatibility workflows.', 1, ?, ?)
                """,
                (chart_id, workspace_id, now, now),
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO accounts (
                    id, workspace_id, account_code, account_name, created_at, chart_id, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (account_id, workspace_id, code, name, now, chart_id, now),
            )
        else:
            connection.execute(
                """
                INSERT OR IGNORE INTO accounts (id, workspace_id, account_code, account_name, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (account_id, workspace_id, code, name, now),
            )
        if owns_transaction:
            connection.commit()
    except sqlite3.DatabaseError as exc:
        if owns_transaction:
            connection.rollback()
        raise PlatformError("Unable to prepare local account reference.") from exc
    return account_id


def user_for_actor(connection: sqlite3.Connection, actor_label: str) -> LocalUser | None:
    """Resolve a local user when the actor label is an existing username."""

    actor = normalize_text(actor_label)
    if not actor:
        return None
    principal = current_server_principal()
    if principal is not None:
        # A server request may only act as the principal that was authenticated
        # for this request. Never fall back to a different local username.
        return principal.user if principal.user.username == actor else None
    try:
        return LocalAuthService(connection).users.get_by_username(actor)
    except (DatabaseError, AuthRepositoryError, AuthServiceError) as exc:
        raise PlatformError("Unable to resolve local actor.") from exc


def require_permission(connection: sqlite3.Connection, *, actor_label: str, permission: str) -> LocalUser | None:
    """Enforce RBAC when the actor is an existing local user.

    Trusted local CLI labels such as ``local-cli`` continue to work only inside the
    explicit trusted-local context. Server request handlers reject unbound actors.
    """

    user = user_for_actor(connection, actor_label)
    if user is None:
        if not is_trusted_local_mode():
            raise PlatformError("Authenticated actor required outside trusted local mode.")
        return None
    principal = current_server_principal()
    if principal is not None:
        decision = CentralPolicyEngine().evaluate(
            PolicyEvaluationContext(
                user_id=principal.user.id,
                username=principal.user.username,
                user_permissions=principal.permissions,
            ),
            required_permission=permission,
        )
        audit_policy_decision(
            decision,
            actor_id=user.id,
            required_permissions=frozenset({permission}),
            surface=f"platform:{permission}",
        )
        if not decision.allowed:
            raise PlatformError("Permission denied for this server workflow action.")
        return user
    try:
        service = LocalAuthService(connection)
        permissions = service.roles.user_permissions(user.username)
        decision = CentralPolicyEngine().evaluate(
            PolicyEvaluationContext(
                user_id=user.id,
                username=user.username,
                user_permissions=permissions,
            ),
            required_permission=permission,
        )
    except (DatabaseError, AuthRepositoryError, AuthServiceError) as exc:
        raise PlatformError("Unable to check local permission.") from exc
    audit_policy_decision(
        decision,
        actor_id=user.id,
        required_permissions=frozenset({permission}),
        surface=f"platform:{permission}",
    )
    if not decision.allowed:
        raise PlatformError("Permission denied for this local workflow action.")
    return user


def audit(
    connection: sqlite3.Connection,
    *,
    actor_label: str,
    object_type: str,
    object_id: str,
    action: str,
    metadata: dict[str, Any] | None = None,
) -> AuditEventReference:
    """Append a sanitized audit event for a platform mutation."""

    user = user_for_actor(connection, actor_label)
    if user is None and not is_trusted_local_mode():
        raise AuditLedgerError("Authenticated actor required outside trusted local mode.")
    safe_metadata = _safe_metadata(metadata or {})
    return append_audit_event(
        connection,
        actor_user_id=user.id if user is not None else None,
        actor_label=actor_label or "local-cli",
        object_type=object_type,
        object_id=object_id,
        action=action,
        metadata=safe_metadata,
    )


def commit_audited(
    connection: sqlite3.Connection,
    *,
    actor_label: str,
    object_type: str,
    object_id: str,
    action: str,
    metadata: dict[str, Any] | None = None,
    emit_outbox: bool = False,
    outbox_event_type: str | None = None,
    outbox_aggregate_type: str | None = None,
    outbox_aggregate_id: str | None = None,
    outbox_payload: dict[str, Any] | None = None,
    outbox_event_id: str | None = None,
) -> None:
    """Append audit evidence and commit one mutation atomically.

    Callers must perform all business writes before invoking this helper and must not
    commit those writes earlier. Any audit or database failure rolls back the caller's
    pending transaction so a business change cannot survive without its evidence.
    """

    if emit_outbox:
        if not outbox_event_type:
            outbox_event_type = action
        if not outbox_aggregate_type:
            outbox_aggregate_type = object_type
        if not outbox_aggregate_id:
            outbox_aggregate_id = object_id
    own_transaction = not connection.in_transaction
    if metadata is None:
        metadata = {}

    try:
        if own_transaction:
            connection.execute("BEGIN IMMEDIATE")
        audit_event = audit(
            connection,
            actor_label=actor_label,
            object_type=object_type,
            object_id=object_id,
            action=action,
            metadata=metadata,
        )
        if emit_outbox:
            safe_event_type = outbox_event_type or action
            safe_aggregate_type = outbox_aggregate_type or object_type
            safe_aggregate_id = outbox_aggregate_id or object_id
            payload = {
                "audit_event_id": audit_event.id,
                **(outbox_payload or {}),
                "object_type": object_type,
                "object_id": object_id,
                "action": action,
            }
            append_outbox_event(
                connection,
                event_id=outbox_event_id or f"OB-{uuid.uuid4().hex}",
                event_type=safe_event_type,
                aggregate_type=safe_aggregate_type,
                aggregate_id=safe_aggregate_id,
                payload=payload,
            )
        connection.commit()
    except (AuditLedgerError, PlatformError, sqlite3.DatabaseError) as exc:
        connection.rollback()
        raise PlatformError("Unable to commit mutation with audit evidence.") from exc


def _safe_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    blocked_fragments = ("password", "secret", "token", "hash", "salt")
    safe: dict[str, Any] = {}
    for key, value in metadata.items():
        lowered = key.lower()
        if any(fragment in lowered for fragment in blocked_fragments):
            continue
        if isinstance(value, str):
            safe[key] = value[:500]
        elif isinstance(value, int | float | bool) or value is None:
            safe[key] = value
        elif isinstance(value, list):
            safe[key] = [str(item)[:160] for item in value[:20]]
        else:
            safe[key] = str(value)[:500]
    return safe


def rows_to_dicts(rows: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
    """Convert SQLite rows to ordinary dictionaries."""

    return [dict(row) for row in rows]
