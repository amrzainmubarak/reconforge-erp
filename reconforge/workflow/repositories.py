"""SQLite repositories for local workflow state."""

from __future__ import annotations

import sqlite3

from reconforge.db.connection import DatabaseError
from reconforge.domain.models import utc_now_text
from reconforge.workflow.models import WorkflowObject, WorkflowTransition, WorkflowTransitionEvent


class WorkflowRepositoryError(ValueError):
    """Raised for safe, user-facing workflow repository errors."""


def ensure_workflow_schema(connection: sqlite3.Connection) -> None:
    """Ensure the local database has the workflow migration applied."""

    try:
        object_columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(workflow_objects)").fetchall()
        }
        transition_columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(workflow_transitions)").fetchall()
        }
        events_table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'workflow_transition_events'",
        ).fetchone()
    except sqlite3.DatabaseError as exc:
        raise DatabaseError("Unable to read ReconForge database. Run 'reconforge db init' first.") from exc
    if not {"id", "created_at", "updated_at"} <= object_columns or not {"reason_required", "active"} <= transition_columns or events_table is None:
        raise DatabaseError("ReconForge workflow schema is not initialized. Run 'reconforge db migrate' first.")


class WorkflowRepository:
    """Repository for local workflow objects, templates, and events."""

    def __init__(self, connection: sqlite3.Connection, *, autocommit: bool = True) -> None:
        ensure_workflow_schema(connection)
        self.connection = connection
        self.autocommit = autocommit

    def list_transitions(self, *, object_type: str, active_only: bool = True) -> list[WorkflowTransition]:
        query = "SELECT * FROM workflow_transitions WHERE object_type = ?"
        params: tuple[object, ...] = (object_type,)
        if active_only:
            query += " AND active = 1"
        query += " ORDER BY from_status, to_status, id"
        try:
            rows = self.connection.execute(query, params).fetchall()
        except sqlite3.DatabaseError as exc:
            raise WorkflowRepositoryError("Unable to list workflow transitions.") from exc
        return [self._row_to_transition(row) for row in rows]

    def get_object(self, *, object_type: str, object_id: str) -> WorkflowObject | None:
        try:
            row = self.connection.execute(
                "SELECT * FROM workflow_objects WHERE object_type = ? AND object_id = ?",
                (object_type, object_id),
            ).fetchone()
        except sqlite3.DatabaseError as exc:
            raise WorkflowRepositoryError("Unable to read workflow object.") from exc
        return self._row_to_object(row) if row is not None else None

    def create_object(self, *, object_type: str, object_id: str, status: str) -> WorkflowObject:
        workflow_object = WorkflowObject(object_type=object_type, object_id=object_id, status=status)
        try:
            self.connection.execute(
                """
                INSERT INTO workflow_objects (id, object_type, object_id, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    workflow_object.id,
                    workflow_object.object_type,
                    workflow_object.object_id,
                    workflow_object.status,
                    workflow_object.created_at,
                    workflow_object.updated_at,
                ),
            )
            if self.autocommit:
                self.connection.commit()
        except sqlite3.IntegrityError as exc:
            raise WorkflowRepositoryError("Workflow object already exists.") from exc
        except sqlite3.DatabaseError as exc:
            raise WorkflowRepositoryError("Unable to create workflow object.") from exc
        return workflow_object

    def update_status(
        self,
        *,
        workflow_object: WorkflowObject,
        status: str,
        autocommit: bool | None = None,
    ) -> WorkflowObject:
        updated_at = utc_now_text()
        should_commit = self.autocommit if autocommit is None else autocommit
        try:
            self.connection.execute(
                """
                UPDATE workflow_objects
                SET status = ?, updated_at = ?
                WHERE object_type = ? AND object_id = ?
                """,
                (status, updated_at, workflow_object.object_type, workflow_object.object_id),
            )
            if should_commit:
                self.connection.commit()
        except sqlite3.DatabaseError as exc:
            raise WorkflowRepositoryError("Unable to update workflow object.") from exc
        return WorkflowObject(
            id=workflow_object.id,
            object_type=workflow_object.object_type,
            object_id=workflow_object.object_id,
            status=status,
            created_at=workflow_object.created_at,
            updated_at=updated_at,
        )

    def record_event(
        self,
        *,
        workflow_object: WorkflowObject,
        from_status: str,
        to_status: str,
        actor_label: str,
        actor_user_id: str | None = None,
        reason: str = "",
        autocommit: bool | None = None,
    ) -> WorkflowTransitionEvent:
        event = WorkflowTransitionEvent(
            workflow_object_id=workflow_object.id,
            from_status=from_status,
            to_status=to_status,
            actor_user_id=actor_user_id,
            actor_label=actor_label,
            reason=reason,
        )
        should_commit = self.autocommit if autocommit is None else autocommit
        try:
            self.connection.execute(
                """
                INSERT INTO workflow_transition_events (
                    id, workflow_object_id, from_status, to_status, actor_user_id, actor_label, reason, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.id,
                    event.workflow_object_id,
                    event.from_status,
                    event.to_status,
                    event.actor_user_id,
                    event.actor_label,
                    event.reason,
                    event.created_at,
                ),
            )
            if should_commit:
                self.connection.commit()
        except sqlite3.DatabaseError as exc:
            raise WorkflowRepositoryError("Unable to record workflow transition event.") from exc
        return event

    def list_events(self, *, workflow_object_id: str) -> list[WorkflowTransitionEvent]:
        try:
            rows = self.connection.execute(
                "SELECT * FROM workflow_transition_events WHERE workflow_object_id = ? ORDER BY created_at, id",
                (workflow_object_id,),
            ).fetchall()
        except sqlite3.DatabaseError as exc:
            raise WorkflowRepositoryError("Unable to list workflow transition history.") from exc
        return [self._row_to_event(row) for row in rows]

    @staticmethod
    def _row_to_object(row: sqlite3.Row) -> WorkflowObject:
        return WorkflowObject(
            id=str(row["id"]),
            object_type=str(row["object_type"]),
            object_id=str(row["object_id"]),
            status=str(row["status"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    @staticmethod
    def _row_to_transition(row: sqlite3.Row) -> WorkflowTransition:
        return WorkflowTransition(
            id=int(row["id"]),
            object_type=str(row["object_type"]),
            from_status=str(row["from_status"]),
            to_status=str(row["to_status"]),
            required_permission=str(row["required_permission"]) if row["required_permission"] is not None else None,
            sod_rule=str(row["sod_rule"]) if row["sod_rule"] is not None else None,
            reason_required=bool(row["reason_required"]),
            active=bool(row["active"]),
        )

    @staticmethod
    def _row_to_event(row: sqlite3.Row) -> WorkflowTransitionEvent:
        return WorkflowTransitionEvent(
            id=str(row["id"]),
            workflow_object_id=str(row["workflow_object_id"]),
            from_status=str(row["from_status"]),
            to_status=str(row["to_status"]),
            actor_user_id=str(row["actor_user_id"]) if row["actor_user_id"] is not None else None,
            actor_label=str(row["actor_label"]),
            reason=str(row["reason"]) if row["reason"] is not None else "",
            created_at=str(row["created_at"]),
        )
