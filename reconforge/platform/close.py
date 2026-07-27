"""DB-backed close management foundations."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from reconforge.close import ALLOWED_CLOSE_STATUSES
from reconforge.domain.control_scores import readiness_percentage
from reconforge.domain.models import utc_now_text
from reconforge.platform.common import (
    PlatformError,
    commit_audited,
    ensure_platform_schema,
    ensure_workspace,
    normalize_key,
    normalize_text,
    platform_id,
    require_permission,
    rows_to_dicts,
)

DEFAULT_CLOSE_TASKS = [
    ("CLOSE-001", "Load trial balance exports", "Data", "high"),
    ("CLOSE-002", "Prepare account reconciliations", "Reconciliations", "high"),
    ("CLOSE-003", "Review unresolved exceptions", "Controls", "high"),
    ("CLOSE-004", "Verify evidence coverage", "Evidence", "medium"),
    ("CLOSE-005", "Review close readiness", "Review", "medium"),
]


@dataclass(frozen=True)
class CloseReadiness:
    """Computed close readiness for a DB close period."""

    period_id: str
    period_name: str
    total_tasks: int
    complete_tasks: int
    blocked_tasks: int
    readiness_score: Decimal


class CloseManagementService:
    """Service for local DB-backed close periods and tasks."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        ensure_platform_schema(connection)
        self.connection = connection

    def period_init(
        self,
        *,
        period_name: str,
        start_date: str,
        end_date: str,
        workspace: str = "default",
        actor_label: str = "local-cli",
        with_default_tasks: bool = True,
    ) -> dict[str, Any]:
        """Create or update a local close period."""

        require_permission(self.connection, actor_label=actor_label, permission="close.manage")
        workspace_id = ensure_workspace(self.connection, workspace)
        period = normalize_key(period_name, default="")
        if not period:
            raise PlatformError("Close period name is required.")
        period_id = platform_id("CP", workspace_id, period)
        now = utc_now_text()
        try:
            self.connection.execute(
                """
                INSERT INTO close_periods (
                    id, workspace_id, period_name, start_date, end_date, status,
                    readiness_score, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, 'Open', 0, ?, ?)
                ON CONFLICT(workspace_id, period_name)
                DO UPDATE SET
                    start_date = excluded.start_date,
                    end_date = excluded.end_date,
                    updated_at = excluded.updated_at
                """,
                (period_id, workspace_id, period, start_date, end_date, now, now),
            )
        except sqlite3.DatabaseError as exc:
            self.connection.rollback()
            raise PlatformError("Unable to initialize close period.") from exc
        if with_default_tasks:
            for code, name, category, risk in DEFAULT_CLOSE_TASKS:
                self.task_add(
                    period_id=period_id,
                    task_code=code,
                    name=name,
                    category=category,
                    risk_rating=risk,
                    actor_label=actor_label,
                    audit_task=False,
                    autocommit=False,
                )
        readiness = self.readiness(period_id=period_id, actor_label=actor_label, audit_read=False, autocommit=False)
        commit_audited(
            self.connection,
            actor_label=actor_label,
            object_type="close_period",
            object_id=period_id,
            action="close_period_initialized",
            metadata={
                "period": period,
                "default_tasks": with_default_tasks,
                "readiness_score": readiness.readiness_score,
            },
        )
        return self.get_period(period_id)

    def task_add(
        self,
        *,
        period_id: str,
        task_code: str,
        name: str,
        owner: str = "",
        category: str = "",
        risk_rating: str = "medium",
        due_date: str = "",
        actor_label: str = "local-cli",
        audit_task: bool = True,
        autocommit: bool = True,
    ) -> dict[str, Any]:
        """Create or update one close task."""

        require_permission(self.connection, actor_label=actor_label, permission="close.manage")
        period = self.get_period(period_id)
        code = normalize_key(task_code, default="")
        if not code:
            raise PlatformError("Close task code is required.")
        task_id = platform_id("CT", period_id, code)
        now = utc_now_text()
        try:
            self.connection.execute(
                """
                INSERT INTO close_tasks_db (
                    id, close_period_id, task_code, name, owner, category, risk_rating,
                    due_date, status, blocker_reason, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Not Started', '', ?, ?)
                ON CONFLICT(close_period_id, task_code)
                DO UPDATE SET
                    name = excluded.name,
                    owner = excluded.owner,
                    category = excluded.category,
                    risk_rating = excluded.risk_rating,
                    due_date = excluded.due_date,
                    updated_at = excluded.updated_at
                """,
                (
                    task_id,
                    period["id"],
                    code,
                    normalize_text(name, default=code),
                    owner,
                    category,
                    normalize_key(risk_rating, default="medium").lower(),
                    due_date,
                    now,
                    now,
                ),
            )
        except sqlite3.DatabaseError as exc:
            self.connection.rollback()
            raise PlatformError("Unable to save close task.") from exc
        if audit_task:
            if autocommit:
                commit_audited(
                    self.connection,
                    actor_label=actor_label,
                    object_type="close_task",
                    object_id=task_id,
                    action="close_task_saved",
                    metadata={"task_code": code, "period": period["period_name"]},
                )
            else:
                commit_audited(
                    self.connection,
                    actor_label=actor_label,
                    object_type="close_task",
                    object_id=task_id,
                    action="close_task_saved",
                    metadata={"task_code": code, "period": period["period_name"]},
                )
        elif autocommit:
            self.connection.commit()
        return self.get_task(task_id)

    def task_dependency(
        self,
        *,
        task_id: str,
        depends_on_task_id: str,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        """Add a close task dependency."""

        require_permission(self.connection, actor_label=actor_label, permission="close.manage")
        task = self.get_task(task_id)
        depends_on = self.get_task(depends_on_task_id)
        if task["close_period_id"] != depends_on["close_period_id"]:
            raise PlatformError("Close task dependencies must be within the same period.")
        dependency_id = platform_id("CTD", task_id, depends_on_task_id)
        now = utc_now_text()
        try:
            self.connection.execute(
                """
                INSERT OR IGNORE INTO close_task_dependencies (
                    id, close_period_id, task_id, depends_on_task_id, created_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (dependency_id, task["close_period_id"], task_id, depends_on_task_id, now),
            )
        except sqlite3.DatabaseError as exc:
            self.connection.rollback()
            raise PlatformError("Unable to save close task dependency.") from exc
        commit_audited(
            self.connection,
            actor_label=actor_label,
            object_type="close_task_dependency",
            object_id=dependency_id,
            action="close_task_dependency_saved",
            metadata={"task_id": task_id, "depends_on_task_id": depends_on_task_id},
        )
        return {"id": dependency_id, "task_id": task_id, "depends_on_task_id": depends_on_task_id}

    def task_status(
        self,
        *,
        task_id: str,
        status: str,
        actor_label: str = "local-cli",
        blocker_reason: str = "",
    ) -> dict[str, Any]:
        """Update one close task status."""

        require_permission(self.connection, actor_label=actor_label, permission="close.manage")
        normalized_status = _allowed_close_status(status)
        task = self.get_task(task_id)
        if normalized_status == "Complete":
            blockers = self._blocking_dependencies(task_id)
            if blockers:
                raise PlatformError("Close task cannot be completed while dependencies are incomplete.")
        now = utc_now_text()
        blocker = normalize_text(blocker_reason) if normalized_status == "Blocked" else ""
        try:
            self.connection.execute(
                """
                UPDATE close_tasks_db
                SET status = ?, blocker_reason = ?, updated_by = ?, updated_at = ?
                WHERE id = ?
                """,
                (normalized_status, blocker, actor_label, now, task_id),
            )
        except sqlite3.DatabaseError as exc:
            self.connection.rollback()
            raise PlatformError("Unable to update close task status.") from exc
        readiness = self.readiness(
            period_id=str(task["close_period_id"]),
            actor_label=actor_label,
            audit_read=False,
            autocommit=False,
        )
        commit_audited(
            self.connection,
            actor_label=actor_label,
            object_type="close_task",
            object_id=task_id,
            action="close_task_status_updated",
            metadata={"status": normalized_status, "readiness_score": readiness.readiness_score},
        )
        return self.get_task(task_id)

    def readiness(
        self,
        *,
        period_id: str,
        actor_label: str = "local-cli",
        audit_read: bool = True,
        autocommit: bool = True,
    ) -> CloseReadiness:
        """Compute and store close readiness for a period."""

        require_permission(self.connection, actor_label=actor_label, permission="close.read")
        period = self.get_period(period_id)
        rows = self.connection.execute(
            "SELECT status FROM close_tasks_db WHERE close_period_id = ?",
            (period_id,),
        ).fetchall()
        total = len(rows)
        complete = sum(1 for row in rows if str(row["status"]) in {"Complete", "Not Applicable"})
        blocked = sum(1 for row in rows if str(row["status"]) == "Blocked")
        score = readiness_percentage(complete=complete, total=total)
        self.connection.execute(
            "UPDATE close_periods SET readiness_score = ?, updated_at = ? WHERE id = ?",
            (str(score), utc_now_text(), period_id),
        )
        if audit_read:
            if autocommit:
                commit_audited(
                    self.connection,
                    actor_label=actor_label,
                    object_type="close_period",
                    object_id=period_id,
                    action="close_readiness_computed",
                    metadata={"readiness_score": str(score), "total_tasks": total, "blocked_tasks": blocked},
                )
            else:
                commit_audited(
                    self.connection,
                    actor_label=actor_label,
                    object_type="close_period",
                    object_id=period_id,
                    action="close_readiness_computed",
                    metadata={"readiness_score": str(score), "total_tasks": total, "blocked_tasks": blocked},
                )
        elif autocommit:
            self.connection.commit()
        return CloseReadiness(
            period_id=period_id,
            period_name=str(period["period_name"]),
            total_tasks=total,
            complete_tasks=complete,
            blocked_tasks=blocked,
            readiness_score=score,
        )

    def lock_period(self, period_id: str, *, actor_label: str = "local-cli") -> dict[str, Any]:
        """Lock a close period when no task is blocked."""

        require_permission(self.connection, actor_label=actor_label, permission="close.manage")
        readiness = self.readiness(period_id=period_id, actor_label=actor_label, audit_read=False, autocommit=False)
        if readiness.blocked_tasks:
            raise PlatformError("Close period cannot be locked while tasks are blocked.")
        now = utc_now_text()
        self.connection.execute(
            "UPDATE close_periods SET status = 'Locked', locked_at = ?, updated_at = ? WHERE id = ?",
            (now, now, period_id),
        )
        commit_audited(
            self.connection,
            actor_label=actor_label,
            object_type="close_period",
            object_id=period_id,
            action="close_period_locked",
            metadata={"readiness_score": readiness.readiness_score},
        )
        return self.get_period(period_id)

    def reopen_period(self, period_id: str, *, reason: str, actor_label: str = "local-cli") -> dict[str, Any]:
        """Reopen a locked period with an audited reason."""

        require_permission(self.connection, actor_label=actor_label, permission="close.manage")
        if not normalize_text(reason):
            raise PlatformError("Reopen reason is required.")
        now = utc_now_text()
        self.connection.execute(
            "UPDATE close_periods SET status = 'Reopened', reopened_at = ?, updated_at = ? WHERE id = ?",
            (now, now, period_id),
        )
        commit_audited(
            self.connection,
            actor_label=actor_label,
            object_type="close_period",
            object_id=period_id,
            action="close_period_reopened",
            metadata={"reason": reason},
        )
        return self.get_period(period_id)

    def list_periods(self) -> list[dict[str, Any]]:
        """List local DB close periods."""

        return rows_to_dicts(
            self.connection.execute(
                "SELECT * FROM close_periods ORDER BY period_name DESC, created_at DESC"
            ).fetchall(),
        )

    def list_tasks(self, *, period_id: str = "", status: str = "", owner: str = "") -> list[dict[str, Any]]:
        """List close tasks with simple queue filters."""

        query = """
            SELECT close_tasks_db.*, close_periods.period_name
            FROM close_tasks_db
            JOIN close_periods ON close_periods.id = close_tasks_db.close_period_id
        """
        filters: list[str] = []
        params: list[object] = []
        if period_id:
            filters.append("close_period_id = ?")
            params.append(period_id)
        if status:
            filters.append("close_tasks_db.status = ?")
            params.append(status)
        if owner:
            filters.append("owner = ?")
            params.append(owner)
        if filters:
            query += " WHERE " + " AND ".join(filters)
        query += " ORDER BY close_periods.period_name DESC, close_tasks_db.task_code"
        return rows_to_dicts(self.connection.execute(query, params).fetchall())

    def get_period(self, period_id: str) -> dict[str, Any]:
        """Read one close period."""

        row = self.connection.execute("SELECT * FROM close_periods WHERE id = ?", (period_id,)).fetchone()
        if row is None:
            raise PlatformError("Close period not found.")
        return dict(row)

    def get_task(self, task_id: str) -> dict[str, Any]:
        """Read one close task."""

        row = self.connection.execute("SELECT * FROM close_tasks_db WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            raise PlatformError("Close task not found.")
        return dict(row)

    def _blocking_dependencies(self, task_id: str) -> list[str]:
        rows = self.connection.execute(
            """
            SELECT dependency.depends_on_task_id
            FROM close_task_dependencies dependency
            JOIN close_tasks_db task ON task.id = dependency.depends_on_task_id
            WHERE dependency.task_id = ? AND task.status NOT IN ('Complete', 'Not Applicable')
            ORDER BY task.task_code
            """,
            (task_id,),
        ).fetchall()
        return [str(row["depends_on_task_id"]) for row in rows]


def _allowed_close_status(status: str) -> str:
    for allowed in ALLOWED_CLOSE_STATUSES:
        if status.lower() == allowed.lower():
            return allowed
    raise PlatformError(f"Invalid close status. Expected one of: {', '.join(ALLOWED_CLOSE_STATUSES)}.")
