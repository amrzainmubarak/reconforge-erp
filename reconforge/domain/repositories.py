"""Minimal SQLite repositories for the local domain backbone."""

from __future__ import annotations

import sqlite3
from typing import Any

from reconforge.audit.events import AuditVerificationResult, append_audit_event, list_audit_events, verify_audit_events
from reconforge.domain.models import DEFAULT_LOCAL_FIRST_NOTE, AuditEventReference, Period, Workspace


class WorkspaceRepository:
    """CRUD helpers for local workspaces."""

    def __init__(self, connection: sqlite3.Connection, *, autocommit: bool = True) -> None:
        self.connection = connection
        self.autocommit = autocommit

    def create(self, *, name: str, local_first_note: str | None = None) -> Workspace:
        workspace = Workspace(name=name, local_first_note=local_first_note or DEFAULT_LOCAL_FIRST_NOTE)
        self.connection.execute(
            "INSERT INTO workspaces (id, name, local_first_note, created_at) VALUES (?, ?, ?, ?)",
            (workspace.id, workspace.name, workspace.local_first_note, workspace.created_at),
        )
        if self.autocommit:
            self.connection.commit()
        return workspace

    def get(self, workspace_id: str) -> Workspace | None:
        row = self.connection.execute("SELECT * FROM workspaces WHERE id = ?", (workspace_id,)).fetchone()
        return self._row_to_workspace(row) if row is not None else None

    def list(self) -> list[Workspace]:
        rows = self.connection.execute("SELECT * FROM workspaces ORDER BY created_at, id").fetchall()
        return [self._row_to_workspace(row) for row in rows]

    @staticmethod
    def _row_to_workspace(row: sqlite3.Row) -> Workspace:
        return Workspace(
            id=str(row["id"]),
            name=str(row["name"]),
            local_first_note=str(row["local_first_note"]),
            created_at=str(row["created_at"]),
        )


class PeriodRepository:
    """CRUD helpers for local periods."""

    def __init__(self, connection: sqlite3.Connection, *, autocommit: bool = True) -> None:
        self.connection = connection
        self.autocommit = autocommit

    def create(
        self,
        *,
        workspace_id: str,
        name: str,
        start_date: str,
        end_date: str,
        status: str = "Open",
    ) -> Period:
        period = Period(workspace_id=workspace_id, name=name, start_date=start_date, end_date=end_date, status=status)
        self.connection.execute(
            """
            INSERT INTO periods (id, workspace_id, name, start_date, end_date, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                period.id,
                period.workspace_id,
                period.name,
                period.start_date,
                period.end_date,
                period.status,
                period.created_at,
            ),
        )
        if self.autocommit:
            self.connection.commit()
        return period

    def get(self, period_id: str) -> Period | None:
        row = self.connection.execute("SELECT * FROM periods WHERE id = ?", (period_id,)).fetchone()
        return self._row_to_period(row) if row is not None else None

    def list(self, *, workspace_id: str | None = None) -> list[Period]:
        if workspace_id is None:
            rows = self.connection.execute("SELECT * FROM periods ORDER BY start_date, id").fetchall()
        else:
            rows = self.connection.execute(
                "SELECT * FROM periods WHERE workspace_id = ? ORDER BY start_date, id",
                (workspace_id,),
            ).fetchall()
        return [self._row_to_period(row) for row in rows]

    @staticmethod
    def _row_to_period(row: sqlite3.Row) -> Period:
        return Period(
            id=str(row["id"]),
            workspace_id=str(row["workspace_id"]),
            name=str(row["name"]),
            start_date=str(row["start_date"]),
            end_date=str(row["end_date"]),
            status=str(row["status"]),
            created_at=str(row["created_at"]),
        )


class AuditEventRepository:
    """Repository wrapper for audit event appends and verification."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def append(
        self,
        *,
        actor_label: str,
        object_type: str,
        object_id: str,
        action: str,
        actor_user_id: str | None = None,
        before_hash: str | None = None,
        after_hash: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AuditEventReference:
        return append_audit_event(
            self.connection,
            actor_label=actor_label,
            object_type=object_type,
            object_id=object_id,
            action=action,
            actor_user_id=actor_user_id,
            before_hash=before_hash,
            after_hash=after_hash,
            metadata=metadata,
        )

    def list(self, *, limit: int | None = None) -> list[AuditEventReference]:
        return list_audit_events(self.connection, limit=limit)

    def verify(self) -> AuditVerificationResult:
        return verify_audit_events(self.connection)
