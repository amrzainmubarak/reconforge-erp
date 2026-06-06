"""Unified DB-backed exception queue foundations."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from typing import Any

from reconforge.domain.models import utc_now_text
from reconforge.platform.common import (
    PlatformError,
    audit,
    ensure_platform_schema,
    ensure_workspace,
    normalize_key,
    normalize_text,
    platform_id,
    require_permission,
    rows_to_dicts,
)

EXCEPTION_STATUSES = {"Open", "In Review", "Resolved", "Accepted Risk", "Closed"}


class ExceptionQueueService:
    """Service for one local queue across finance workflow sources."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        ensure_platform_schema(connection)
        self.connection = connection

    def upsert_exception(
        self,
        *,
        source_type: str,
        source_id: str,
        description: str,
        workspace: str = "default",
        period_name: str = "",
        entity_code: str = "",
        account_code: str = "",
        control_code: str = "",
        risk_rating: str = "medium",
        owner: str = "",
        status: str = "Open",
        escalation_level: str = "",
        sla_target_date: str = "",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        """Create or update one queue record."""

        require_permission(self.connection, actor_label=actor_label, permission="exceptions.manage")
        workspace_id = ensure_workspace(self.connection, workspace)
        source = normalize_key(source_type, default="")
        source_key = normalize_key(source_id, default="")
        if not source or not source_key:
            raise PlatformError("Exception source type and source id are required.")
        status_value = _allowed_status(status)
        exception_id = platform_id("EXQ", workspace_id, source, source_key)
        now = utc_now_text()
        try:
            self.connection.execute(
                """
                INSERT INTO exceptions_queue (
                    id, workspace_id, source_type, source_id, period_name, entity_code,
                    account_code, control_code, risk_rating, owner, status, escalation_level,
                    sla_target_date, description, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(workspace_id, source_type, source_id)
                DO UPDATE SET
                    period_name = excluded.period_name,
                    entity_code = excluded.entity_code,
                    account_code = excluded.account_code,
                    control_code = excluded.control_code,
                    risk_rating = excluded.risk_rating,
                    owner = excluded.owner,
                    status = excluded.status,
                    escalation_level = excluded.escalation_level,
                    sla_target_date = excluded.sla_target_date,
                    description = excluded.description,
                    updated_at = excluded.updated_at
                """,
                (
                    exception_id,
                    workspace_id,
                    source,
                    source_key,
                    period_name,
                    entity_code,
                    account_code,
                    control_code,
                    normalize_key(risk_rating, default="medium").lower(),
                    owner,
                    status_value,
                    escalation_level,
                    sla_target_date,
                    normalize_text(description),
                    now,
                    now,
                ),
            )
            self.connection.commit()
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to save exception queue record.") from exc
        audit(
            self.connection,
            actor_label=actor_label,
            object_type="exception",
            object_id=exception_id,
            action="exception_saved",
            metadata={"source_type": source, "source_id": source_key, "risk_rating": risk_rating, "status": status_value},
        )
        return self.get(exception_id)

    def list(
        self,
        *,
        period_name: str = "",
        entity_code: str = "",
        account_code: str = "",
        control_code: str = "",
        risk_rating: str = "",
        owner: str = "",
        status: str = "",
    ) -> list[dict[str, Any]]:
        """List queue records by common finance dimensions."""

        return rows_to_dicts(
            self.connection.execute(
                """
                SELECT * FROM exceptions_queue
                WHERE (? = '' OR period_name = ?)
                  AND (? = '' OR entity_code = ?)
                  AND (? = '' OR account_code = ?)
                  AND (? = '' OR control_code = ?)
                  AND (? = '' OR risk_rating = ?)
                  AND (? = '' OR owner = ?)
                  AND (? = '' OR status = ?)
                ORDER BY risk_rating DESC, created_at DESC
                """,
                (
                    period_name,
                    period_name,
                    entity_code,
                    entity_code,
                    account_code,
                    account_code,
                    control_code,
                    control_code,
                    risk_rating,
                    risk_rating,
                    owner,
                    owner,
                    status,
                    status,
                ),
            ).fetchall(),
        )

    def assign(self, exception_id: str, *, owner: str, actor_label: str = "local-cli") -> dict[str, Any]:
        """Assign a queue record."""

        require_permission(self.connection, actor_label=actor_label, permission="exceptions.manage")
        if not normalize_text(owner):
            raise PlatformError("Exception owner is required.")
        self._update_fields(exception_id, {"owner": owner, "updated_at": utc_now_text()})
        audit(
            self.connection,
            actor_label=actor_label,
            object_type="exception",
            object_id=exception_id,
            action="exception_assigned",
            metadata={"owner": owner},
        )
        return self.get(exception_id)

    def set_status(self, exception_id: str, *, status: str, actor_label: str = "local-cli") -> dict[str, Any]:
        """Set one queue status."""

        require_permission(self.connection, actor_label=actor_label, permission="exceptions.manage")
        status_value = _allowed_status(status)
        self._update_fields(exception_id, {"status": status_value, "updated_at": utc_now_text()})
        audit(
            self.connection,
            actor_label=actor_label,
            object_type="exception",
            object_id=exception_id,
            action="exception_status_updated",
            metadata={"status": status_value},
        )
        return self.get(exception_id)

    def bulk_update(
        self,
        exception_ids: Sequence[str],
        *,
        status: str = "",
        owner: str = "",
        actor_label: str = "local-cli",
    ) -> int:
        """Bulk-update status and/or owner for selected queue records."""

        require_permission(self.connection, actor_label=actor_label, permission="exceptions.manage")
        updates: dict[str, Any] = {"updated_at": utc_now_text()}
        if status:
            updates["status"] = _allowed_status(status)
        if owner:
            updates["owner"] = owner
        if len(updates) == 1:
            raise PlatformError("Bulk update requires status or owner.")
        count = 0
        for exception_id in exception_ids:
            self._update_fields(exception_id, updates)
            count += 1
        audit(
            self.connection,
            actor_label=actor_label,
            object_type="exception",
            object_id="bulk",
            action="exception_bulk_updated",
            metadata={"count": count, "status": status, "owner": owner},
        )
        return count

    def get(self, exception_id: str) -> dict[str, Any]:
        """Read one queue record."""

        row = self.connection.execute("SELECT * FROM exceptions_queue WHERE id = ?", (exception_id,)).fetchone()
        if row is None:
            raise PlatformError("Exception queue record not found.")
        return dict(row)

    def _update_fields(self, exception_id: str, updates: dict[str, Any]) -> None:
        allowed = {"owner", "status", "updated_at"}
        if not set(updates) <= allowed:
            raise PlatformError("Unsupported exception update.")
        try:
            self.connection.execute(
                """
                UPDATE exceptions_queue
                SET owner = COALESCE(?, owner),
                    status = COALESCE(?, status),
                    updated_at = ?
                WHERE id = ?
                """,
                (updates.get("owner"), updates.get("status"), updates["updated_at"], exception_id),
            )
            self.connection.commit()
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to update exception queue record.") from exc


def _allowed_status(status: str) -> str:
    for allowed in EXCEPTION_STATUSES:
        if status.lower() == allowed.lower():
            return allowed
    raise PlatformError(f"Invalid exception status. Expected one of: {', '.join(sorted(EXCEPTION_STATUSES))}.")
