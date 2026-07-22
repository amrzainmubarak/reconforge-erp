"""Shared helpers for local DB-backed finance workflows."""

from __future__ import annotations

import csv
import json
import sqlite3
from collections.abc import Iterable
from datetime import date
from hashlib import sha256
from pathlib import Path
from typing import Any

from reconforge.audit import append_audit_event
from reconforge.auth import AuthRepositoryError, AuthServiceError, LocalAuthService
from reconforge.auth.models import LocalUser
from reconforge.db.connection import DatabaseError
from reconforge.db.exporter import resolve_input_file
from reconforge.domain.models import DEFAULT_LOCAL_FIRST_NOTE, utc_now_text
from reconforge.utils.time import utc_today


class PlatformError(ValueError):
    """Raised for safe, user-facing platform workflow errors."""


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


def to_float(value: object, *, default: float = 0.0) -> float:
    """Parse a local numeric value safely."""

    if value is None:
        return default
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return default


def to_int(value: object, *, default: int = 0) -> int:
    """Parse a local integer value safely."""

    if value is None:
        return default
    try:
        return int(float(str(value).replace(",", "").strip()))
    except (TypeError, ValueError):
        return default


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


def date_diff_days(left: object, right: object) -> int:
    """Return absolute day difference for two date-like values."""

    left_date = parse_date(left)
    right_date = parse_date(right)
    if left_date is None or right_date is None:
        return 0
    return abs((left_date - right_date).days)


def read_local_records(input_path: Path | str) -> tuple[Path, list[dict[str, Any]]]:
    """Read a local CSV or JSON record file without executing content."""

    resolved = resolve_input_file(input_path)
    suffix = resolved.suffix.lower()
    try:
        if suffix == ".csv":
            with resolved.open("r", encoding="utf-8-sig", newline="") as handle:
                return resolved, [dict(row) for row in csv.DictReader(handle)]
        if suffix == ".json":
            payload = json.loads(resolved.read_text(encoding="utf-8"))
        else:
            raise PlatformError("Input file must be CSV or JSON.")
    except (OSError, csv.Error, json.JSONDecodeError) as exc:
        raise PlatformError("Unable to read local input records.") from exc
    if isinstance(payload, list):
        records = payload
    elif isinstance(payload, dict):
        value = payload.get("records") or payload.get("rows") or payload.get("items") or payload.get("data")
        records = value if isinstance(value, list) else [payload]
    else:
        raise PlatformError("JSON input must contain an object or list of objects.")
    clean_records: list[dict[str, Any]] = []
    for record in records:
        if isinstance(record, dict):
            clean_records.append(dict(record))
    return resolved, clean_records


def ensure_workspace(connection: sqlite3.Connection, workspace: str = "default") -> str:
    """Create or return a local workspace reference."""

    ensure_platform_schema(connection)
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
        connection.commit()
    except sqlite3.DatabaseError as exc:
        raise PlatformError("Unable to prepare local workspace reference.") from exc
    return workspace_id


def ensure_account(connection: sqlite3.Connection, *, workspace_id: str, account_code: str, account_name: str) -> str:
    """Create or return a local account reference."""

    code = normalize_key(account_code, default="UNKNOWN")
    name = normalize_text(account_name, default=code)
    account_id = platform_id("ACC", workspace_id, code)
    now = utc_now_text()
    try:
        account_columns = {
            str(row["name"]) for row in connection.execute("PRAGMA table_info(accounts)").fetchall()
        }
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
        connection.commit()
    except sqlite3.DatabaseError as exc:
        raise PlatformError("Unable to prepare local account reference.") from exc
    return account_id


def user_for_actor(connection: sqlite3.Connection, actor_label: str) -> LocalUser | None:
    """Resolve a local user when the actor label is an existing username."""

    actor = normalize_text(actor_label)
    if not actor:
        return None
    try:
        return LocalAuthService(connection).users.get_by_username(actor)
    except (DatabaseError, AuthRepositoryError, AuthServiceError) as exc:
        raise PlatformError("Unable to resolve local actor.") from exc


def require_permission(connection: sqlite3.Connection, *, actor_label: str, permission: str) -> LocalUser | None:
    """Enforce RBAC when the actor is an existing local user.

    Trusted local CLI labels such as ``local-cli`` continue to work without a user record.
    API and auth-required Studio actions pass real usernames, so RBAC is enforced there.
    """

    user = user_for_actor(connection, actor_label)
    if user is None:
        return None
    try:
        allowed = LocalAuthService(connection).user_has_permission(username=user.username, permission=permission)
    except (DatabaseError, AuthRepositoryError, AuthServiceError) as exc:
        raise PlatformError("Unable to check local permission.") from exc
    if not allowed:
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
) -> None:
    """Append a sanitized audit event for a platform mutation."""

    user = user_for_actor(connection, actor_label)
    safe_metadata = _safe_metadata(metadata or {})
    append_audit_event(
        connection,
        actor_user_id=user.id if user is not None else None,
        actor_label=actor_label or "local-cli",
        object_type=object_type,
        object_id=object_id,
        action=action,
        metadata=safe_metadata,
    )


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
