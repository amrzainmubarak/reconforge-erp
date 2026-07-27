"""Tenant-scoped PostgreSQL close-control metadata.

This boundary tracks close work performed in ReconForge.  A locked close
period here is an application workflow state; it does not lock postings in a
source ERP or imply statutory period close.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

from reconforge.domain.control_scores import COMPLETE_READINESS, readiness_percentage
from reconforge.infrastructure.postgres import PostgresConfigurationError, normalize_scope_id, validate_tenant_id
from reconforge.infrastructure.postgres_ledger import (
    _hash_payload,
    _json_text,
    _record,
    _row_value,
)
from reconforge.io.persisted import PersistedJsonError, encode_postgres_outbox_payload
from reconforge.utils.time import utc_now_text


class PostgresCloseValidationError(ValueError):
    """Raised when close-control input is invalid."""


class PostgresCloseIntegrityError(RuntimeError):
    """Raised when close-control data conflicts with an existing record."""


class PostgresCloseNotFoundError(PostgresCloseIntegrityError):
    """Raised when a requested close-control record does not exist."""


def _outbox_json_text(value: Mapping[str, object]) -> str:
    try:
        return encode_postgres_outbox_payload(value).text
    except PersistedJsonError as exc:
        raise PostgresCloseValidationError("outbox payload must be JSON-serializable.") from exc


_ID_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,63}$"
_CLOSE_STATUSES = ("Open", "Under Review", "Approved", "Locked", "Reopened", "Archived")
_TASK_STATUSES = ("Not Started", "In Progress", "Blocked", "Complete", "Not Applicable")
_RISK_RATINGS = ("low", "medium", "high", "critical")
_PERIOD_TRANSITIONS = {
    "Open": {"Under Review", "Locked", "Reopened"},
    "Under Review": {"Approved", "Reopened"},
    "Approved": {"Locked", "Reopened"},
    "Locked": {"Reopened", "Archived"},
    "Reopened": {"Under Review"},
    "Archived": set(),
}
POSTGRES_DEFAULT_CLOSE_TASKS = (
    ("CLOSE-001", "Load trial balance exports", "Data", "high"),
    ("CLOSE-002", "Prepare account reconciliations", "Reconciliations", "high"),
    ("CLOSE-003", "Review unresolved exceptions", "Controls", "high"),
    ("CLOSE-004", "Verify evidence coverage", "Evidence", "medium"),
    ("CLOSE-005", "Review close readiness", "Review", "medium"),
)

_PERIOD_COLUMNS = (
    "tenant_id",
    "id",
    "fiscal_period_id",
    "organization_id",
    "status",
    "readiness_score",
    "created_at",
    "updated_at",
    "locked_at",
    "reopened_at",
)
_TASK_COLUMNS = (
    "tenant_id",
    "id",
    "close_period_id",
    "task_code",
    "name",
    "owner_user_id",
    "category",
    "risk_rating",
    "due_date",
    "status",
    "blocker_reason",
    "updated_by",
    "created_at",
    "updated_at",
)


def _tenant_id(value: str) -> str:
    try:
        return validate_tenant_id(value)
    except PostgresConfigurationError as exc:
        raise PostgresCloseValidationError(str(exc)) from exc


def _scope_id(value: object, field_name: str) -> str:
    try:
        normalized = normalize_scope_id(str(value), field_name=field_name)
    except PostgresConfigurationError as exc:
        raise PostgresCloseValidationError(str(exc)) from exc
    import re
    if not re.fullmatch(_ID_PATTERN, normalized):
        raise PostgresCloseValidationError(f"{field_name} has an invalid identifier.")
    return normalized


def _text(value: object, field_name: str, *, maximum: int = 255) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise PostgresCloseValidationError(f"{field_name} must not be blank.")
    if len(normalized) > maximum:
        raise PostgresCloseValidationError(f"{field_name} must be at most {maximum} characters.")
    if any(ord(character) < 32 or ord(character) == 127 for character in normalized):
        raise PostgresCloseValidationError(f"{field_name} must contain printable characters only.")
    return " ".join(normalized.split())


def _optional_text(value: object, field_name: str, *, maximum: int = 255) -> str:
    if value is None or not str(value).strip():
        return ""
    return _text(value, field_name, maximum=maximum)


def _code(value: object, field_name: str) -> str:
    normalized = _text(value, field_name, maximum=64).upper()
    import re

    if not re.fullmatch(r"[A-Z0-9][A-Z0-9._/-]{0,63}", normalized):
        raise PostgresCloseValidationError(f"{field_name} contains unsupported characters.")
    return normalized


def _choice(value: object, field_name: str, choices: tuple[str, ...]) -> str:
    normalized = _text(value, field_name, maximum=40).casefold()
    for choice in choices:
        if normalized == choice.casefold():
            return choice
    raise PostgresCloseValidationError(f"{field_name} must be one of: {', '.join(choices)}.")


def _date(value: object, field_name: str, *, optional: bool = False) -> str:
    raw = str(value or "").strip()
    if optional and not raw:
        return ""
    try:
        parsed = date.fromisoformat(raw)
    except ValueError as exc:
        raise PostgresCloseValidationError(f"{field_name} must use YYYY-MM-DD format.") from exc
    if parsed.isoformat() != raw:
        raise PostgresCloseValidationError(f"{field_name} must use YYYY-MM-DD format.")
    return raw


def _record_or_not_found(row: Any, columns: tuple[str, ...], message: str) -> dict[str, Any]:
    if row is None:
        raise PostgresCloseNotFoundError(message)
    return _record(row, columns)


@dataclass(frozen=True)
class PostgresCloseRepository:
    """Persist close-control records in a caller-owned tenant transaction."""

    connection: Any

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
        reason: str = "",
        metadata: Mapping[str, object] | None = None,
    ) -> None:
        if actor_id is None:
            return
        tenant = _tenant_id(tenant_id)
        actor = _text(actor_id, "actor_id", maximum=160)
        request = _optional_text(request_id, "request_id", maximum=160)
        audit_reason = _optional_text(reason, "reason", maximum=500)
        metadata_json = _json_text(metadata, "metadata")
        after_state_hash = _hash_payload(after_state)
        outbox_payload_json = _outbox_json_text(
            {"resource_type": resource_type, "resource_id": resource_id, "after_state_hash": after_state_hash}
        )
        self.connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (tenant,))
        event_id = _hash_payload(
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
        previous_hash = "" if previous_row is None else str(_row_value(previous_row, "event_hash", 0) or "")
        occurred_at = utc_now_text()
        event_hash = _hash_payload(
            {
                "tenant_id": tenant,
                "event_id": event_id,
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
                 request_id, before_state_hash, after_state_hash, previous_event_hash, event_hash, reason, metadata)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CAST(%s AS jsonb))
            ON CONFLICT (tenant_id, event_id) DO NOTHING
            """,
            (
                tenant,
                event_id,
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
        outbox_id = _hash_payload(
            {"tenant_id": tenant, "event_type": f"close.{action}", "resource_id": resource_id}
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
                outbox_id,
                f"close.{action}",
                resource_type,
                resource_id,
                outbox_payload_json,
            ),
        )

    def _period(self, *, tenant_id: str, period_id: str) -> dict[str, Any]:
        tenant = _tenant_id(tenant_id)
        identifier = _scope_id(period_id, "close_period_id")
        cursor = self.connection.execute(
            """
            SELECT tenant_id, id, fiscal_period_id, organization_id, status,
                   readiness_score, created_at, updated_at, locked_at, reopened_at
            FROM reconforge.close_periods
            WHERE tenant_id = %s AND id = %s
            """,
            (tenant, identifier),
        )
        return _record_or_not_found(cursor.fetchone(), _PERIOD_COLUMNS, "Close period was not found.")

    def create_period(
        self,
        *,
        tenant_id: str,
        period_id: str,
        fiscal_period_id: str,
        organization_id: str,
        organization_code: str,
        expected_start_date: str = "",
        expected_end_date: str = "",
        actor_id: str | None = None,
        request_id: str = "",
        metadata: Mapping[str, object] | None = None,
    ) -> dict[str, Any]:
        tenant = _tenant_id(tenant_id)
        identifier = _scope_id(period_id, "close_period_id")
        fiscal_period = _scope_id(fiscal_period_id, "fiscal_period_id")
        organization = _scope_id(organization_id, "organization_id")
        code = _code(organization_code, "organization_code")
        period_cursor = self.connection.execute(
            "SELECT id, name, start_date, end_date FROM reconforge.fiscal_periods WHERE tenant_id = %s AND id = %s",
            (tenant, fiscal_period),
        )
        period_row = period_cursor.fetchone()
        if period_row is None:
            raise PostgresCloseNotFoundError("Fiscal period was not found.")
        expected_start = _date(expected_start_date, "start_date", optional=True)
        expected_end = _date(expected_end_date, "end_date", optional=True)
        if expected_start and str(_row_value(period_row, "start_date", 2)) != expected_start:
            raise PostgresCloseValidationError("start_date does not match the PostgreSQL fiscal period.")
        if expected_end and str(_row_value(period_row, "end_date", 3)) != expected_end:
            raise PostgresCloseValidationError("end_date does not match the PostgreSQL fiscal period.")
        organization_cursor = self.connection.execute(
            """
            SELECT id, organization_code, active
            FROM reconforge.organizations
            WHERE tenant_id = %s AND id = %s AND organization_code = %s
            """,
            (tenant, organization, code),
        )
        organization_row = organization_cursor.fetchone()
        if organization_row is None:
            raise PostgresCloseNotFoundError("Organization was not found.")
        if not bool(_row_value(organization_row, "active", 2)):
            raise PostgresCloseValidationError("Close control requires an active organization.")
        before_cursor = self.connection.execute(
            "SELECT tenant_id, id, fiscal_period_id, organization_id, status, readiness_score, created_at, updated_at, locked_at, reopened_at FROM reconforge.close_periods WHERE tenant_id = %s AND id = %s",
            (tenant, identifier),
        )
        before_row = before_cursor.fetchone()
        before_hash = "" if before_row is None else _hash_payload(_record(before_row, _PERIOD_COLUMNS))
        now = utc_now_text()
        cursor = self.connection.execute(
            """
            INSERT INTO reconforge.close_periods
                (tenant_id, id, fiscal_period_id, organization_id, status, readiness_score, created_at, updated_at)
            VALUES (%s, %s, %s, %s, 'Open', 0, %s, %s)
            ON CONFLICT (tenant_id, fiscal_period_id, organization_id) DO UPDATE SET updated_at = EXCLUDED.updated_at
            RETURNING tenant_id, id, fiscal_period_id, organization_id, status,
                      readiness_score, created_at, updated_at, locked_at, reopened_at
            """,
            (tenant, identifier, fiscal_period, organization, now, now),
        )
        record = _record_or_not_found(cursor.fetchone(), _PERIOD_COLUMNS, "Close period could not be created.")
        self._append_evidence(
            tenant_id=tenant,
            actor_id=actor_id,
            request_id=request_id,
            action="close_period_created",
            resource_type="close_period",
            resource_id=str(record["id"]),
            before_state_hash=before_hash,
            after_state=record,
            metadata={"fiscal_period_id": fiscal_period, "organization_code": code, **dict(metadata or {})},
        )
        return self.get_period(tenant_id=tenant, period_id=str(record["id"]))

    def list_periods(self, *, tenant_id: str) -> list[dict[str, Any]]:
        tenant = _tenant_id(tenant_id)
        cursor = self.connection.execute(
            """
            SELECT close_periods.tenant_id, close_periods.id, close_periods.fiscal_period_id,
                   close_periods.organization_id, organizations.organization_code,
                   fiscal_periods.name AS fiscal_period_name, fiscal_periods.start_date,
                   fiscal_periods.end_date, close_periods.status, close_periods.readiness_score,
                   close_periods.created_at, close_periods.updated_at, close_periods.locked_at,
                   close_periods.reopened_at
            FROM reconforge.close_periods
            JOIN reconforge.fiscal_periods
              ON fiscal_periods.tenant_id = close_periods.tenant_id
             AND fiscal_periods.id = close_periods.fiscal_period_id
            JOIN reconforge.organizations
              ON organizations.tenant_id = close_periods.tenant_id
             AND organizations.id = close_periods.organization_id
            WHERE close_periods.tenant_id = %s
            ORDER BY fiscal_periods.start_date DESC, organizations.organization_code, close_periods.id
            """,
            (tenant,),
        )
        columns = (
            "tenant_id", "id", "fiscal_period_id", "organization_id", "organization_code",
            "fiscal_period_name", "start_date", "end_date", "status", "readiness_score",
            "created_at", "updated_at", "locked_at", "reopened_at",
        )
        return [_record(row, columns) for row in cursor.fetchall()]

    def organization_by_code(self, *, tenant_id: str, organization_code: str) -> dict[str, Any]:
        tenant = _tenant_id(tenant_id)
        code = _code(organization_code, "organization_code")
        cursor = self.connection.execute(
            """
            SELECT tenant_id, id, organization_code, name, base_currency, active
            FROM reconforge.organizations
            WHERE tenant_id = %s AND organization_code = %s
            """,
            (tenant, code),
        )
        return _record_or_not_found(
            cursor.fetchone(),
            ("tenant_id", "id", "organization_code", "name", "base_currency", "active"),
            "Organization was not found.",
        )

    def get_period(self, *, tenant_id: str, period_id: str) -> dict[str, Any]:
        return self._period(tenant_id=tenant_id, period_id=period_id)

    def upsert_task(
        self,
        *,
        tenant_id: str,
        task_id: str,
        close_period_id: str,
        task_code: str,
        name: str,
        owner_user_id: str = "",
        category: str = "",
        risk_rating: str = "medium",
        due_date: str = "",
        actor_id: str | None = None,
        request_id: str = "",
        metadata: Mapping[str, object] | None = None,
    ) -> dict[str, Any]:
        tenant = _tenant_id(tenant_id)
        identifier = _scope_id(task_id, "task_id")
        period = self._period(tenant_id=tenant, period_id=close_period_id)
        code = _code(task_code, "task_code")
        task_name = _text(name, "task name", maximum=255)
        owner = _optional_text(owner_user_id, "owner_user_id", maximum=160)
        category_value = _optional_text(category, "category", maximum=80)
        risk = _choice(risk_rating, "risk_rating", _RISK_RATINGS)
        due = _date(due_date, "due_date", optional=True)
        before_cursor = self.connection.execute(
            """
            SELECT tenant_id, id, close_period_id, task_code, name, owner_user_id, category,
                   risk_rating, due_date, status, blocker_reason, updated_by, created_at, updated_at
            FROM reconforge.close_tasks WHERE tenant_id = %s AND id = %s
            """,
            (tenant, identifier),
        )
        before_row = before_cursor.fetchone()
        before_hash = "" if before_row is None else _hash_payload(_record(before_row, _TASK_COLUMNS))
        now = utc_now_text()
        cursor = self.connection.execute(
            """
            INSERT INTO reconforge.close_tasks
                (tenant_id, id, close_period_id, task_code, name, owner_user_id, category,
                 risk_rating, due_date, status, blocker_reason, updated_by, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NULLIF(%s, '')::date, 'Not Started', '', %s, %s, %s)
            ON CONFLICT (tenant_id, id) DO UPDATE SET
                name = EXCLUDED.name,
                owner_user_id = EXCLUDED.owner_user_id,
                category = EXCLUDED.category,
                risk_rating = EXCLUDED.risk_rating,
                due_date = EXCLUDED.due_date,
                updated_by = EXCLUDED.updated_by,
                updated_at = EXCLUDED.updated_at
            RETURNING tenant_id, id, close_period_id, task_code, name, owner_user_id, category,
                      risk_rating, due_date, status, blocker_reason, updated_by, created_at, updated_at
            """,
            (tenant, identifier, str(period["id"]), code, task_name, owner, category_value, risk, due, owner, now, now),
        )
        record = _record_or_not_found(cursor.fetchone(), _TASK_COLUMNS, "Close task could not be saved.")
        self._append_evidence(
            tenant_id=tenant,
            actor_id=actor_id,
            request_id=request_id,
            action="close_task_saved",
            resource_type="close_task",
            resource_id=str(record["id"]),
            before_state_hash=before_hash,
            after_state=record,
            metadata={"task_code": code, "close_period_id": str(period["id"]), **dict(metadata or {})},
        )
        return record

    def list_tasks(
        self,
        *,
        tenant_id: str,
        close_period_id: str = "",
        status: str = "",
        owner_user_id: str = "",
    ) -> list[dict[str, Any]]:
        tenant = _tenant_id(tenant_id)
        query = """
            SELECT tasks.tenant_id, tasks.id, tasks.close_period_id, tasks.task_code, tasks.name,
                   tasks.owner_user_id, tasks.category, tasks.risk_rating, tasks.due_date,
                   tasks.status, tasks.blocker_reason, tasks.updated_by, tasks.created_at, tasks.updated_at,
                   periods.fiscal_period_id
            FROM reconforge.close_tasks AS tasks
            JOIN reconforge.close_periods AS periods
              ON periods.tenant_id = tasks.tenant_id AND periods.id = tasks.close_period_id
            WHERE tasks.tenant_id = %s
        """
        parameters: list[Any] = [tenant]
        if close_period_id.strip():
            query += " AND tasks.close_period_id = %s"
            parameters.append(_scope_id(close_period_id, "close_period_id"))
        if status.strip():
            query += " AND tasks.status = %s"
            parameters.append(_choice(status, "status", _TASK_STATUSES))
        if owner_user_id.strip():
            query += " AND tasks.owner_user_id = %s"
            parameters.append(_optional_text(owner_user_id, "owner_user_id", maximum=160))
        query += " ORDER BY tasks.close_period_id, tasks.task_code, tasks.id"
        cursor = self.connection.execute(query, tuple(parameters))
        columns = _TASK_COLUMNS + ("fiscal_period_id",)
        return [_record(row, columns) for row in cursor.fetchall()]

    def set_task_status(
        self,
        *,
        tenant_id: str,
        task_id: str,
        status: str,
        actor_id: str,
        blocker_reason: str = "",
        request_id: str = "",
        metadata: Mapping[str, object] | None = None,
    ) -> dict[str, Any]:
        tenant = _tenant_id(tenant_id)
        identifier = _scope_id(task_id, "task_id")
        actor = _text(actor_id, "actor_id", maximum=160)
        selected = _choice(status, "status", _TASK_STATUSES)
        task = self._task(tenant_id=tenant, task_id=identifier)
        period = self._period(tenant_id=tenant, period_id=str(task["close_period_id"]))
        if str(period["status"]) in {"Locked", "Archived"}:
            raise PostgresCloseValidationError("Close tasks cannot change after the close period is locked or archived.")
        blocker = _optional_text(blocker_reason, "blocker_reason", maximum=500) if selected == "Blocked" else ""
        if selected == "Complete":
            blockers = self.connection.execute(
                """
                SELECT dependency.depends_on_task_id
                FROM reconforge.close_task_dependencies AS dependency
                JOIN reconforge.close_tasks AS dependency_task
                  ON dependency_task.tenant_id = dependency.tenant_id
                 AND dependency_task.id = dependency.depends_on_task_id
                WHERE dependency.tenant_id = %s AND dependency.task_id = %s
                  AND dependency_task.status NOT IN ('Complete', 'Not Applicable')
                ORDER BY dependency.depends_on_task_id
                """,
                (tenant, identifier),
            ).fetchall()
            if blockers:
                raise PostgresCloseValidationError("Close task cannot be completed while dependencies are incomplete.")
        now = utc_now_text()
        cursor = self.connection.execute(
            """
            UPDATE reconforge.close_tasks
            SET status = %s, blocker_reason = %s, updated_by = %s, updated_at = %s
            WHERE tenant_id = %s AND id = %s
            RETURNING tenant_id, id, close_period_id, task_code, name, owner_user_id, category,
                      risk_rating, due_date, status, blocker_reason, updated_by, created_at, updated_at
            """,
            (selected, blocker, actor, now, tenant, identifier),
        )
        record = _record_or_not_found(cursor.fetchone(), _TASK_COLUMNS, "Close task was not found.")
        self._append_evidence(
            tenant_id=tenant,
            actor_id=actor,
            request_id=request_id,
            action="close_task_status_updated",
            resource_type="close_task",
            resource_id=identifier,
            before_state_hash=_hash_payload(task),
            after_state=record,
            metadata={"status": selected, **dict(metadata or {})},
        )
        return record

    def _task(self, *, tenant_id: str, task_id: str) -> dict[str, Any]:
        tenant = _tenant_id(tenant_id)
        identifier = _scope_id(task_id, "task_id")
        cursor = self.connection.execute(
            """
            SELECT tenant_id, id, close_period_id, task_code, name, owner_user_id, category,
                   risk_rating, due_date, status, blocker_reason, updated_by, created_at, updated_at
            FROM reconforge.close_tasks WHERE tenant_id = %s AND id = %s
            """,
            (tenant, identifier),
        )
        return _record_or_not_found(cursor.fetchone(), _TASK_COLUMNS, "Close task was not found.")

    def readiness(self, *, tenant_id: str, period_id: str) -> dict[str, Any]:
        tenant = _tenant_id(tenant_id)
        period = self._period(tenant_id=tenant, period_id=period_id)
        rows = self.connection.execute(
            "SELECT status FROM reconforge.close_tasks WHERE tenant_id = %s AND close_period_id = %s",
            (tenant, str(period["id"])),
        ).fetchall()
        total = len(rows)
        complete = sum(1 for row in rows if str(_row_value(row, "status", 0)) in {"Complete", "Not Applicable"})
        blocked = sum(1 for row in rows if str(_row_value(row, "status", 0)) == "Blocked")
        score = readiness_percentage(complete=complete, total=total)
        self.connection.execute(
            "UPDATE reconforge.close_periods SET readiness_score = %s, updated_at = %s WHERE tenant_id = %s AND id = %s",
            (score, utc_now_text(), tenant, str(period["id"])),
        )
        return {
            "period_id": period["id"],
            "period_name": period["fiscal_period_id"],
            "total_tasks": total,
            "complete_tasks": complete,
            "blocked_tasks": blocked,
            "readiness_score": score,
        }

    def set_period_status(
        self,
        *,
        tenant_id: str,
        period_id: str,
        status: str,
        actor_id: str,
        reason: str = "",
        request_id: str = "",
        metadata: Mapping[str, object] | None = None,
    ) -> dict[str, Any]:
        tenant = _tenant_id(tenant_id)
        identifier = _scope_id(period_id, "close_period_id")
        actor = _text(actor_id, "actor_id", maximum=160)
        selected = _choice(status, "status", _CLOSE_STATUSES)
        period = self._period(tenant_id=tenant, period_id=identifier)
        current = str(period["status"])
        if selected != current and selected not in _PERIOD_TRANSITIONS.get(current, set()):
            raise PostgresCloseValidationError(f"Invalid close-period transition: {current} -> {selected}.")
        clean_reason = _optional_text(reason, "reason", maximum=500)
        if selected == "Reopened" and not clean_reason:
            raise PostgresCloseValidationError("Reopening a close period requires a reason.")
        if selected in {"Approved", "Locked"}:
            readiness = self.readiness(tenant_id=tenant, period_id=identifier)
            if readiness["readiness_score"] != COMPLETE_READINESS:
                raise PostgresCloseValidationError("A close period cannot be approved or locked before all tasks are complete.")
        now = utc_now_text()
        cursor = self.connection.execute(
            """
            UPDATE reconforge.close_periods
            SET status = %s,
                locked_at = CASE WHEN %s = 'Locked' THEN %s ELSE locked_at END,
                reopened_at = CASE WHEN %s = 'Reopened' THEN %s ELSE reopened_at END,
                updated_at = %s
            WHERE tenant_id = %s AND id = %s
            RETURNING tenant_id, id, fiscal_period_id, organization_id, status,
                      readiness_score, created_at, updated_at, locked_at, reopened_at
            """,
            (selected, selected, now, selected, now, now, tenant, identifier),
        )
        record = _record_or_not_found(cursor.fetchone(), _PERIOD_COLUMNS, "Close period was not found.")
        self._append_evidence(
            tenant_id=tenant,
            actor_id=actor,
            request_id=request_id,
            action="close_period_status_updated",
            resource_type="close_period",
            resource_id=identifier,
            before_state_hash=_hash_payload(period),
            after_state=record,
            reason=clean_reason,
            metadata={"from_status": current, "to_status": selected, **dict(metadata or {})},
        )
        return self.get_period(tenant_id=tenant, period_id=identifier)


POSTGRES_CLOSE_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS reconforge.close_periods (
    tenant_id TEXT NOT NULL,
    id TEXT NOT NULL,
    fiscal_period_id TEXT NOT NULL,
    organization_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Open',
    readiness_score NUMERIC(5,2) NOT NULL DEFAULT 0 CHECK (readiness_score >= 0 AND readiness_score <= 100),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    locked_at TIMESTAMPTZ,
    reopened_at TIMESTAMPTZ,
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, fiscal_period_id, organization_id),
    FOREIGN KEY (tenant_id, fiscal_period_id)
        REFERENCES reconforge.fiscal_periods(tenant_id, id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id, organization_id)
        REFERENCES reconforge.organizations(tenant_id, id) ON DELETE RESTRICT,
    CHECK (status IN ('Open', 'Under Review', 'Approved', 'Locked', 'Reopened', 'Archived'))
);

CREATE TABLE IF NOT EXISTS reconforge.close_tasks (
    tenant_id TEXT NOT NULL,
    id TEXT NOT NULL,
    close_period_id TEXT NOT NULL,
    task_code TEXT NOT NULL,
    name TEXT NOT NULL,
    owner_user_id TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT '',
    risk_rating TEXT NOT NULL DEFAULT 'medium',
    due_date DATE,
    status TEXT NOT NULL DEFAULT 'Not Started',
    blocker_reason TEXT NOT NULL DEFAULT '',
    updated_by TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, close_period_id, task_code),
    FOREIGN KEY (tenant_id, close_period_id)
        REFERENCES reconforge.close_periods(tenant_id, id) ON DELETE CASCADE,
    CHECK (risk_rating IN ('low', 'medium', 'high', 'critical')),
    CHECK (status IN ('Not Started', 'In Progress', 'Blocked', 'Complete', 'Not Applicable'))
);

CREATE TABLE IF NOT EXISTS reconforge.close_task_dependencies (
    tenant_id TEXT NOT NULL,
    id TEXT NOT NULL,
    close_period_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    depends_on_task_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, task_id, depends_on_task_id),
    FOREIGN KEY (tenant_id, close_period_id)
        REFERENCES reconforge.close_periods(tenant_id, id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id, task_id)
        REFERENCES reconforge.close_tasks(tenant_id, id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id, depends_on_task_id)
        REFERENCES reconforge.close_tasks(tenant_id, id) ON DELETE CASCADE,
    CHECK (task_id <> depends_on_task_id)
);

CREATE INDEX IF NOT EXISTS idx_close_periods_tenant_status
    ON reconforge.close_periods (tenant_id, status, fiscal_period_id);
CREATE INDEX IF NOT EXISTS idx_close_tasks_tenant_queue
    ON reconforge.close_tasks (tenant_id, close_period_id, status, owner_user_id, task_code);
CREATE INDEX IF NOT EXISTS idx_close_dependencies_tenant_task
    ON reconforge.close_task_dependencies (tenant_id, task_id, depends_on_task_id);

ALTER TABLE reconforge.close_periods ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.close_periods FORCE ROW LEVEL SECURITY;
ALTER TABLE reconforge.close_tasks ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.close_tasks FORCE ROW LEVEL SECURITY;
ALTER TABLE reconforge.close_task_dependencies ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.close_task_dependencies FORCE ROW LEVEL SECURITY;

DO $reconforge$
DECLARE
    table_name TEXT;
BEGIN
    FOREACH table_name IN ARRAY ARRAY['close_periods', 'close_tasks', 'close_task_dependencies']
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
