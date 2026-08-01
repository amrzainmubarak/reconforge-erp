"""Contract-compatible tenant-scoped PostgreSQL close-management aggregate."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import date
from typing import Any

from reconforge.application.close import CloseReadiness
from reconforge.domain.control_scores import COMPLETE_READINESS, readiness_percentage
from reconforge.infrastructure.postgres import set_local_tenant_scope, validate_tenant_id
from reconforge.infrastructure.postgres_domain import PostgresAuditEventRepository
from reconforge.io.persisted import PersistedJsonError, encode_postgres_outbox_payload
from reconforge.platform.common import PlatformError, normalize_key, normalize_text, platform_id

POSTGRES_CLOSE_APPLICATION_SCHEMA_SQL = r"""
CREATE TABLE IF NOT EXISTS reconforge.close_application_periods (
 tenant_id TEXT NOT NULL,id TEXT NOT NULL,workspace_id TEXT NOT NULL,period_name TEXT NOT NULL,
 start_date DATE NOT NULL,end_date DATE NOT NULL,status TEXT NOT NULL DEFAULT 'Open'
 CHECK(status IN('Open','Locked','Reopened')),readiness_score NUMERIC(5,2) NOT NULL DEFAULT 0
 CHECK(readiness_score>=0 AND readiness_score<=100),created_by TEXT NOT NULL,
 locked_by TEXT NOT NULL DEFAULT '',locked_at TIMESTAMPTZ,reopened_by TEXT NOT NULL DEFAULT '',
 reopened_at TIMESTAMPTZ,reopen_reason TEXT NOT NULL DEFAULT '',created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),row_version BIGINT NOT NULL DEFAULT 1 CHECK(row_version>0),
 PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,workspace_id,period_name),
 FOREIGN KEY(tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id) ON DELETE CASCADE,
 CHECK(start_date<=end_date)
);
CREATE TABLE IF NOT EXISTS reconforge.close_application_tasks (
 tenant_id TEXT NOT NULL,id TEXT NOT NULL,close_period_id TEXT NOT NULL,task_code TEXT NOT NULL,
 name TEXT NOT NULL,owner TEXT NOT NULL DEFAULT '',category TEXT NOT NULL DEFAULT '',
 risk_rating TEXT NOT NULL DEFAULT 'medium' CHECK(risk_rating IN('low','medium','high','critical')),
 due_date DATE,status TEXT NOT NULL DEFAULT 'Not Started'
 CHECK(status IN('Not Started','In Progress','Blocked','Complete','Not Applicable')),
 blocker_reason TEXT NOT NULL DEFAULT '',updated_by TEXT NOT NULL DEFAULT '',created_by TEXT NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 row_version BIGINT NOT NULL DEFAULT 1 CHECK(row_version>0),PRIMARY KEY(tenant_id,id),
 UNIQUE(tenant_id,close_period_id,task_code),
 FOREIGN KEY(tenant_id,close_period_id) REFERENCES reconforge.close_application_periods(tenant_id,id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS reconforge.close_application_dependencies (
 tenant_id TEXT NOT NULL,id TEXT NOT NULL,close_period_id TEXT NOT NULL,task_id TEXT NOT NULL,
 depends_on_task_id TEXT NOT NULL,created_by TEXT NOT NULL,created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,task_id,depends_on_task_id),
 FOREIGN KEY(tenant_id,close_period_id) REFERENCES reconforge.close_application_periods(tenant_id,id) ON DELETE CASCADE,
 FOREIGN KEY(tenant_id,task_id) REFERENCES reconforge.close_application_tasks(tenant_id,id) ON DELETE CASCADE,
 FOREIGN KEY(tenant_id,depends_on_task_id) REFERENCES reconforge.close_application_tasks(tenant_id,id) ON DELETE CASCADE,
 CHECK(task_id<>depends_on_task_id)
);
CREATE INDEX IF NOT EXISTS close_application_period_queue_idx ON reconforge.close_application_periods
 (tenant_id,workspace_id,status,period_name,id);
CREATE INDEX IF NOT EXISTS close_application_task_queue_idx ON reconforge.close_application_tasks
 (tenant_id,close_period_id,status,owner,task_code,id);

CREATE OR REPLACE FUNCTION reconforge.close_application_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE period_status TEXT; task_period TEXT; dependency_period TEXT;
BEGIN
 IF TG_TABLE_NAME='close_application_periods' THEN
  IF TG_OP='INSERT' AND (NEW.status<>'Open' OR NEW.locked_by<>'' OR NEW.locked_at IS NOT NULL OR NEW.reopened_by<>'' OR NEW.reopened_at IS NOT NULL OR NEW.reopen_reason<>'') THEN RAISE EXCEPTION 'close periods require complete Open metadata'; END IF;
  IF TG_OP='UPDATE' AND NEW.status<>OLD.status AND NOT ((OLD.status IN('Open','Reopened') AND NEW.status='Locked') OR (OLD.status='Locked' AND NEW.status='Reopened')) THEN RAISE EXCEPTION 'invalid close period status transition'; END IF;
  IF TG_OP='UPDATE' AND OLD.status IN('Open','Reopened') AND NEW.status='Locked' AND (NEW.locked_by='' OR NEW.locked_at IS NULL OR NEW.readiness_score<>100 OR EXISTS(SELECT 1 FROM reconforge.close_application_tasks t WHERE t.tenant_id=OLD.tenant_id AND t.close_period_id=OLD.id AND t.status NOT IN('Complete','Not Applicable'))) THEN RAISE EXCEPTION 'locking a close period requires complete tasks and actor evidence'; END IF;
  IF TG_OP='UPDATE' AND OLD.status='Locked' AND NEW.status='Reopened' AND (NEW.reopened_by='' OR NEW.reopened_at IS NULL OR NEW.reopen_reason='') THEN RAISE EXCEPTION 'reopening a close period requires actor reason and timestamp'; END IF;
  IF TG_OP='UPDATE' AND OLD.status='Locked' AND (NEW.workspace_id,NEW.period_name,NEW.start_date,NEW.end_date,NEW.created_by,NEW.created_at,NEW.locked_by,NEW.locked_at) IS DISTINCT FROM (OLD.workspace_id,OLD.period_name,OLD.start_date,OLD.end_date,OLD.created_by,OLD.created_at,OLD.locked_by,OLD.locked_at) THEN RAISE EXCEPTION 'locked close period scope and lock evidence are immutable'; END IF;
  IF TG_OP='DELETE' AND OLD.status<>'Open' THEN RAISE EXCEPTION 'locked or reopened close periods cannot be deleted'; END IF;
  IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;
 END IF;
 IF TG_TABLE_NAME='close_application_tasks' THEN
  IF TG_OP='DELETE' THEN SELECT status INTO period_status FROM reconforge.close_application_periods WHERE tenant_id=OLD.tenant_id AND id=OLD.close_period_id; ELSE SELECT status INTO period_status FROM reconforge.close_application_periods WHERE tenant_id=NEW.tenant_id AND id=NEW.close_period_id; END IF;
  IF period_status='Locked' THEN RAISE EXCEPTION 'tasks in a locked close period are immutable'; END IF;
  IF TG_OP='UPDATE' AND (NEW.close_period_id,NEW.task_code,NEW.created_by,NEW.created_at) IS DISTINCT FROM (OLD.close_period_id,OLD.task_code,OLD.created_by,OLD.created_at) THEN RAISE EXCEPTION 'close task identity evidence is immutable'; END IF;
  IF TG_OP<>'DELETE' AND ((NEW.status='Blocked' AND NEW.blocker_reason='') OR (NEW.status<>'Blocked' AND NEW.blocker_reason<>'')) THEN RAISE EXCEPTION 'blocked close tasks require an exclusive blocker reason'; END IF;
  IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;
 END IF;
 IF TG_OP='DELETE' THEN SELECT status INTO period_status FROM reconforge.close_application_periods WHERE tenant_id=OLD.tenant_id AND id=OLD.close_period_id; IF period_status='Locked' THEN RAISE EXCEPTION 'dependencies in a locked close period are immutable'; END IF; RETURN OLD; END IF;
 SELECT close_period_id INTO task_period FROM reconforge.close_application_tasks WHERE tenant_id=NEW.tenant_id AND id=NEW.task_id;
 SELECT close_period_id INTO dependency_period FROM reconforge.close_application_tasks WHERE tenant_id=NEW.tenant_id AND id=NEW.depends_on_task_id;
 SELECT status INTO period_status FROM reconforge.close_application_periods WHERE tenant_id=NEW.tenant_id AND id=NEW.close_period_id;
 IF period_status='Locked' OR task_period IS DISTINCT FROM NEW.close_period_id OR dependency_period IS DISTINCT FROM NEW.close_period_id THEN RAISE EXCEPTION 'close task dependencies require one unlocked period'; END IF;
 IF EXISTS(WITH RECURSIVE path(task_id) AS (SELECT depends_on_task_id FROM reconforge.close_application_dependencies WHERE tenant_id=NEW.tenant_id AND task_id=NEW.depends_on_task_id UNION SELECT d.depends_on_task_id FROM reconforge.close_application_dependencies d JOIN path p ON d.task_id=p.task_id WHERE d.tenant_id=NEW.tenant_id) SELECT 1 FROM path WHERE task_id=NEW.task_id) THEN RAISE EXCEPTION 'close task dependency would create a cycle'; END IF;
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS close_application_periods_guard ON reconforge.close_application_periods;
CREATE TRIGGER close_application_periods_guard BEFORE INSERT OR UPDATE OR DELETE ON reconforge.close_application_periods FOR EACH ROW EXECUTE FUNCTION reconforge.close_application_guard();
DROP TRIGGER IF EXISTS close_application_tasks_guard ON reconforge.close_application_tasks;
CREATE TRIGGER close_application_tasks_guard BEFORE INSERT OR UPDATE OR DELETE ON reconforge.close_application_tasks FOR EACH ROW EXECUTE FUNCTION reconforge.close_application_guard();
DROP TRIGGER IF EXISTS close_application_dependencies_guard ON reconforge.close_application_dependencies;
CREATE TRIGGER close_application_dependencies_guard BEFORE INSERT OR UPDATE OR DELETE ON reconforge.close_application_dependencies FOR EACH ROW EXECUTE FUNCTION reconforge.close_application_guard();

DO $rls$ DECLARE table_name TEXT; BEGIN
 FOREACH table_name IN ARRAY ARRAY['close_application_periods','close_application_tasks','close_application_dependencies'] LOOP
  EXECUTE format('ALTER TABLE reconforge.%I ENABLE ROW LEVEL SECURITY',table_name); EXECUTE format('ALTER TABLE reconforge.%I FORCE ROW LEVEL SECURITY',table_name);
  EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON reconforge.%I',table_name);
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname='reconforge' AND tablename=table_name AND policyname='tenant_scope') THEN
   EXECUTE format('CREATE POLICY tenant_isolation ON reconforge.%I USING (tenant_id=current_setting(''app.tenant_id'',true)) WITH CHECK (tenant_id=current_setting(''app.tenant_id'',true))',table_name);
  END IF;
 END LOOP;
END $rls$;
"""

DEFAULT_CLOSE_TASKS = (
    ("CLOSE-001", "Load trial balance exports", "Data", "high"),
    ("CLOSE-002", "Prepare account reconciliations", "Reconciliations", "high"),
    ("CLOSE-003", "Review unresolved exceptions", "Controls", "high"),
    ("CLOSE-004", "Verify evidence coverage", "Evidence", "medium"),
    ("CLOSE-005", "Review close readiness", "Review", "medium"),
)
TASK_STATUSES = ("Not Started", "In Progress", "Blocked", "Complete", "Not Applicable")


class PostgresCloseApplicationError(RuntimeError):
    """Safe contract-compatible close persistence failure."""


def _iso_date(value: object, field: str, *, optional: bool = False) -> str:
    raw = str(value or "").strip()
    if optional and not raw:
        return ""
    try:
        parsed = date.fromisoformat(raw)
    except ValueError as exc:
        raise PlatformError(f"{field} must use YYYY-MM-DD format.") from exc
    if parsed.isoformat() != raw:
        raise PlatformError(f"{field} must use YYYY-MM-DD format.")
    return raw


def _choice(value: object, field: str, choices: tuple[str, ...]) -> str:
    raw = normalize_text(value, default="")
    for choice in choices:
        if raw.casefold() == choice.casefold():
            return choice
    raise PlatformError(f"{field} must be one of: {', '.join(choices)}.")


class PostgresCloseManagementRepository:
    """Implement the complete close-management Application port for one tenant."""

    def __init__(self, connection: Any, tenant_id: str) -> None:
        self.connection = connection
        self.tenant_id = validate_tenant_id(tenant_id)

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        try:
            with self.connection.transaction():
                set_local_tenant_scope(self.connection, self.tenant_id)
                yield
        except (PlatformError, PostgresCloseApplicationError):
            raise
        except Exception as exc:
            raise PostgresCloseApplicationError("PostgreSQL close-management operation failed.") from exc

    def _event(
        self,
        *,
        actor_label: str,
        object_type: str,
        object_id: str,
        action: str,
        version: object,
        metadata: Mapping[str, object],
    ) -> None:
        actor = normalize_text(actor_label, default="local-cli")
        PostgresAuditEventRepository(self.connection, self.tenant_id).append(
            actor_label=actor,
            object_type=object_type,
            object_id=object_id,
            action=action,
            metadata=dict(metadata),
        )
        event_id = platform_id("OBX", action, object_id, version)
        try:
            payload = encode_postgres_outbox_payload(dict(metadata)).text
        except PersistedJsonError as exc:
            raise PlatformError("Unable to encode close-management evidence.") from exc
        self.connection.execute(
            """INSERT INTO reconforge.outbox_events(tenant_id,event_id,event_type,aggregate_type,aggregate_id,payload)
            VALUES(%s,%s,%s,%s,%s,CAST(%s AS jsonb)) ON CONFLICT(tenant_id,event_id) DO NOTHING""",
            (self.tenant_id, event_id, action, object_type, object_id, payload),
        )

    def _workspace_id(self, workspace: str) -> str:
        row = self.connection.execute(
            "SELECT id FROM reconforge.domain_workspaces WHERE tenant_id=%s AND name=%s",
            (self.tenant_id, normalize_text(workspace, default="default")),
        ).fetchone()
        if row is None:
            raise PlatformError("Workspace was not found for this tenant.")
        return str(row["id"])

    def _period(self, period_id: str, *, lock: bool = False) -> dict[str, Any]:
        query = (
            "SELECT * FROM reconforge.close_application_periods WHERE tenant_id=%s AND id=%s FOR UPDATE"
            if lock
            else "SELECT * FROM reconforge.close_application_periods WHERE tenant_id=%s AND id=%s"
        )
        row = self.connection.execute(query, (self.tenant_id, normalize_text(period_id, default=""))).fetchone()
        if row is None:
            raise PlatformError("Close period not found.")
        result = dict(row)
        result["readiness_score"] = str(result["readiness_score"])
        return result

    def _task(self, task_id: str, *, lock: bool = False) -> dict[str, Any]:
        query = (
            "SELECT * FROM reconforge.close_application_tasks WHERE tenant_id=%s AND id=%s FOR UPDATE"
            if lock
            else "SELECT * FROM reconforge.close_application_tasks WHERE tenant_id=%s AND id=%s"
        )
        row = self.connection.execute(query, (self.tenant_id, normalize_text(task_id, default=""))).fetchone()
        if row is None:
            raise PlatformError("Close task not found.")
        return dict(row)

    def _task_add(
        self,
        *,
        period_id: str,
        task_code: str,
        name: str,
        owner: str,
        category: str,
        risk_rating: str,
        due_date: str,
        actor_label: str,
        audit_task: bool,
    ) -> dict[str, Any]:
        period = self._period(period_id, lock=True)
        if period["status"] == "Locked":
            raise PlatformError("Tasks cannot be changed while the close period is Locked.")
        code = normalize_key(task_code, default="")
        if not code:
            raise PlatformError("Close task code is required.")
        risk = _choice(risk_rating, "Risk rating", ("low", "medium", "high", "critical"))
        due = _iso_date(due_date, "Due date", optional=True)
        task_id = platform_id("CT", period_id, code)
        row = self.connection.execute(
            """INSERT INTO reconforge.close_application_tasks(
            tenant_id,id,close_period_id,task_code,name,owner,category,risk_rating,due_date,
            status,blocker_reason,created_by)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,NULLIF(%s,'')::date,'Not Started','',%s)
            ON CONFLICT(tenant_id,close_period_id,task_code) DO UPDATE SET
            name=EXCLUDED.name,owner=EXCLUDED.owner,category=EXCLUDED.category,
            risk_rating=EXCLUDED.risk_rating,due_date=EXCLUDED.due_date,updated_by=EXCLUDED.created_by,
            updated_at=now(),row_version=reconforge.close_application_tasks.row_version+1
            RETURNING id,row_version""",
            (
                self.tenant_id,
                task_id,
                period_id,
                code,
                normalize_text(name, default=code),
                normalize_text(owner, default=""),
                normalize_text(category, default=""),
                risk,
                due,
                normalize_text(actor_label, default="local-cli"),
            ),
        ).fetchone()
        if row is None:
            raise PlatformError("Unable to save close task.")
        if audit_task:
            self._event(
                actor_label=actor_label,
                object_type="close_task",
                object_id=task_id,
                action="close_task_saved",
                version=row["row_version"],
                metadata={"task_code": code, "period": period["period_name"]},
            )
        return self._task(task_id)

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
        period = normalize_key(period_name, default="")
        if not period:
            raise PlatformError("Close period name is required.")
        start = _iso_date(start_date, "Start date")
        end = _iso_date(end_date, "End date")
        if start > end:
            raise PlatformError("Close period start date must not be after end date.")
        with self._transaction():
            workspace_id = self._workspace_id(workspace)
            self.connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                (f"close-period|{workspace_id}",),
            )
            overlap = self.connection.execute(
                """SELECT 1 FROM reconforge.close_application_periods WHERE tenant_id=%s AND workspace_id=%s
                AND period_name<>%s AND daterange(start_date,end_date,'[]') && daterange(%s::date,%s::date,'[]') LIMIT 1""",
                (self.tenant_id, workspace_id, period, start, end),
            ).fetchone()
            if overlap is not None:
                raise PlatformError("Close period dates overlap another period in this workspace.")
            period_id = platform_id("CP", workspace_id, period)
            row = self.connection.execute(
                """INSERT INTO reconforge.close_application_periods(
                tenant_id,id,workspace_id,period_name,start_date,end_date,status,readiness_score,created_by)
                VALUES(%s,%s,%s,%s,%s,%s,'Open',0,%s)
                ON CONFLICT(tenant_id,workspace_id,period_name) DO UPDATE SET
                start_date=EXCLUDED.start_date,end_date=EXCLUDED.end_date,updated_at=now(),
                row_version=reconforge.close_application_periods.row_version+1
                WHERE reconforge.close_application_periods.status IN('Open','Reopened') RETURNING id,row_version""",
                (
                    self.tenant_id,
                    period_id,
                    workspace_id,
                    period,
                    start,
                    end,
                    normalize_text(actor_label, default="local-cli"),
                ),
            ).fetchone()
            if row is None:
                raise PlatformError("Locked close periods cannot be reinitialized.")
            if with_default_tasks:
                for code, task_name, category, risk in DEFAULT_CLOSE_TASKS:
                    self._task_add(
                        period_id=period_id,
                        task_code=code,
                        name=task_name,
                        owner="",
                        category=category,
                        risk_rating=risk,
                        due_date="",
                        actor_label=actor_label,
                        audit_task=False,
                    )
            readiness = self._readiness(period_id)
            self._event(
                actor_label=actor_label,
                object_type="close_period",
                object_id=period_id,
                action="close_period_initialized",
                version=row["row_version"],
                metadata={
                    "period": period,
                    "default_tasks": with_default_tasks,
                    "readiness_score": str(readiness.readiness_score),
                },
            )
            return self._period(period_id)

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
        del autocommit
        with self._transaction():
            return self._task_add(
                period_id=period_id,
                task_code=task_code,
                name=name,
                owner=owner,
                category=category,
                risk_rating=risk_rating,
                due_date=due_date,
                actor_label=actor_label,
                audit_task=audit_task,
            )

    def task_dependency(
        self,
        *,
        task_id: str,
        depends_on_task_id: str,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        with self._transaction():
            task = self._task(task_id, lock=True)
            dependency = self._task(depends_on_task_id, lock=True)
            if task["close_period_id"] != dependency["close_period_id"]:
                raise PlatformError("Close task dependencies must be within the same period.")
            if task_id == depends_on_task_id:
                raise PlatformError("Close task dependency would create a cycle.")
            cycle = self.connection.execute(
                """WITH RECURSIVE path(task_id) AS (
                SELECT depends_on_task_id FROM reconforge.close_application_dependencies
                WHERE tenant_id=%s AND task_id=%s UNION
                SELECT d.depends_on_task_id FROM reconforge.close_application_dependencies d
                JOIN path p ON d.task_id=p.task_id WHERE d.tenant_id=%s)
                SELECT 1 FROM path WHERE task_id=%s LIMIT 1""",
                (self.tenant_id, depends_on_task_id, self.tenant_id, task_id),
            ).fetchone()
            if cycle is not None:
                raise PlatformError("Close task dependency would create a cycle.")
            dependency_id = platform_id("CTD", task_id, depends_on_task_id)
            self.connection.execute(
                """INSERT INTO reconforge.close_application_dependencies(
                tenant_id,id,close_period_id,task_id,depends_on_task_id,created_by)
                VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(tenant_id,task_id,depends_on_task_id) DO NOTHING""",
                (
                    self.tenant_id,
                    dependency_id,
                    task["close_period_id"],
                    task_id,
                    depends_on_task_id,
                    normalize_text(actor_label, default="local-cli"),
                ),
            )
            self._event(
                actor_label=actor_label,
                object_type="close_task_dependency",
                object_id=dependency_id,
                action="close_task_dependency_saved",
                version="created",
                metadata={"task_id": task_id, "depends_on_task_id": depends_on_task_id},
            )
            return {"id": dependency_id, "task_id": task_id, "depends_on_task_id": depends_on_task_id}

    def _readiness(self, period_id: str) -> CloseReadiness:
        period = self._period(period_id)
        rows = self.connection.execute(
            "SELECT status FROM reconforge.close_application_tasks WHERE tenant_id=%s AND close_period_id=%s",
            (self.tenant_id, period_id),
        ).fetchall()
        total = len(rows)
        complete = sum(str(row["status"]) in {"Complete", "Not Applicable"} for row in rows)
        blocked = sum(str(row["status"]) == "Blocked" for row in rows)
        score = readiness_percentage(complete=complete, total=total)
        self.connection.execute(
            """UPDATE reconforge.close_application_periods SET readiness_score=%s,updated_at=now(),
            row_version=row_version+1 WHERE tenant_id=%s AND id=%s""",
            (score, self.tenant_id, period_id),
        )
        return CloseReadiness(period_id, str(period["period_name"]), total, complete, blocked, score)

    def task_status(
        self,
        *,
        task_id: str,
        status: str,
        actor_label: str = "local-cli",
        blocker_reason: str = "",
    ) -> dict[str, Any]:
        selected = _choice(status, "Close status", TASK_STATUSES)
        blocker = normalize_text(blocker_reason, default="") if selected == "Blocked" else ""
        if selected == "Blocked" and not blocker:
            raise PlatformError("Blocked close tasks require a blocker reason.")
        with self._transaction():
            task = self._task(task_id, lock=True)
            period = self._period(str(task["close_period_id"]), lock=True)
            if period["status"] == "Locked":
                raise PlatformError("Tasks in a locked close period are immutable.")
            if selected == "Complete":
                incomplete = self.connection.execute(
                    """SELECT 1 FROM reconforge.close_application_dependencies d
                    JOIN reconforge.close_application_tasks t ON t.tenant_id=d.tenant_id AND t.id=d.depends_on_task_id
                    WHERE d.tenant_id=%s AND d.task_id=%s AND t.status NOT IN('Complete','Not Applicable') LIMIT 1""",
                    (self.tenant_id, task_id),
                ).fetchone()
                if incomplete is not None:
                    raise PlatformError("Close task cannot be completed while dependencies are incomplete.")
            row = self.connection.execute(
                """UPDATE reconforge.close_application_tasks SET status=%s,blocker_reason=%s,
                updated_by=%s,updated_at=now(),row_version=row_version+1 WHERE tenant_id=%s AND id=%s
                RETURNING row_version""",
                (selected, blocker, normalize_text(actor_label, default="local-cli"), self.tenant_id, task_id),
            ).fetchone()
            if row is None:
                raise PlatformError("Close task changed concurrently; reload and retry.")
            readiness = self._readiness(str(task["close_period_id"]))
            self._event(
                actor_label=actor_label,
                object_type="close_task",
                object_id=task_id,
                action="close_task_status_updated",
                version=row["row_version"],
                metadata={"status": selected, "readiness_score": str(readiness.readiness_score)},
            )
            return self._task(task_id)

    def readiness(
        self,
        *,
        period_id: str,
        actor_label: str = "local-cli",
        audit_read: bool = True,
        autocommit: bool = True,
    ) -> CloseReadiness:
        del autocommit
        with self._transaction():
            result = self._readiness(period_id)
            if audit_read:
                period = self._period(period_id)
                self._event(
                    actor_label=actor_label,
                    object_type="close_period",
                    object_id=period_id,
                    action="close_readiness_computed",
                    version=period["row_version"],
                    metadata={
                        "readiness_score": str(result.readiness_score),
                        "total_tasks": result.total_tasks,
                        "blocked_tasks": result.blocked_tasks,
                    },
                )
            return result

    def lock_period(self, period_id: str, *, actor_label: str = "local-cli") -> dict[str, Any]:
        actor = normalize_text(actor_label, default="local-cli")
        with self._transaction():
            period = self._period(period_id, lock=True)
            if period["status"] not in {"Open", "Reopened"}:
                raise PlatformError("Only Open or Reopened close periods can be locked.")
            readiness = self._readiness(period_id)
            if readiness.readiness_score != COMPLETE_READINESS:
                raise PlatformError("Close period cannot be locked before all tasks are complete.")
            row = self.connection.execute(
                """UPDATE reconforge.close_application_periods SET status='Locked',locked_by=%s,
                locked_at=now(),updated_at=now(),row_version=row_version+1
                WHERE tenant_id=%s AND id=%s AND status IN('Open','Reopened') RETURNING row_version""",
                (actor, self.tenant_id, period_id),
            ).fetchone()
            if row is None:
                raise PlatformError("Close period changed concurrently; reload and retry.")
            self._event(
                actor_label=actor,
                object_type="close_period",
                object_id=period_id,
                action="close_period_locked",
                version=row["row_version"],
                metadata={"readiness_score": str(readiness.readiness_score)},
            )
            return self._period(period_id)

    def reopen_period(self, period_id: str, *, reason: str, actor_label: str = "local-cli") -> dict[str, Any]:
        reopen_reason = normalize_text(reason, default="")
        if not reopen_reason:
            raise PlatformError("Reopen reason is required.")
        actor = normalize_text(actor_label, default="local-cli")
        with self._transaction():
            period = self._period(period_id, lock=True)
            if period["status"] != "Locked":
                raise PlatformError("Only Locked close periods can be reopened.")
            row = self.connection.execute(
                """UPDATE reconforge.close_application_periods SET status='Reopened',reopened_by=%s,
                reopened_at=now(),reopen_reason=%s,updated_at=now(),row_version=row_version+1
                WHERE tenant_id=%s AND id=%s AND status='Locked' RETURNING row_version""",
                (actor, reopen_reason, self.tenant_id, period_id),
            ).fetchone()
            if row is None:
                raise PlatformError("Close period changed concurrently; reload and retry.")
            self._event(
                actor_label=actor,
                object_type="close_period",
                object_id=period_id,
                action="close_period_reopened",
                version=row["row_version"],
                metadata={"reason": reopen_reason},
            )
            return self._period(period_id)

    def list_periods(self) -> list[dict[str, Any]]:
        with self._transaction():
            rows = self.connection.execute(
                """SELECT * FROM reconforge.close_application_periods WHERE tenant_id=%s
                ORDER BY period_name DESC,created_at DESC,id DESC LIMIT 10000""",
                (self.tenant_id,),
            ).fetchall()
            result: list[dict[str, Any]] = []
            for raw in rows:
                row = dict(raw)
                row["readiness_score"] = str(row["readiness_score"])
                result.append(row)
            return result

    def list_tasks(self, *, period_id: str = "", status: str = "", owner: str = "") -> list[dict[str, Any]]:
        selected = _choice(status, "Close status", TASK_STATUSES) if status else ""
        with self._transaction():
            rows = self.connection.execute(
                """SELECT t.*,p.period_name FROM reconforge.close_application_tasks t
                JOIN reconforge.close_application_periods p ON p.tenant_id=t.tenant_id AND p.id=t.close_period_id
                WHERE t.tenant_id=%s AND (%s='' OR t.close_period_id=%s)
                AND (%s='' OR t.status=%s) AND (%s='' OR t.owner=%s)
                ORDER BY p.period_name DESC,t.task_code,t.id LIMIT 10000""",
                (self.tenant_id, period_id, period_id, selected, selected, owner, owner),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_period(self, period_id: str) -> dict[str, Any]:
        with self._transaction():
            return self._period(period_id)

    def get_task(self, task_id: str) -> dict[str, Any]:
        with self._transaction():
            return self._task(task_id)
