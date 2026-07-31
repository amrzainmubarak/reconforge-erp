"""Contract-compatible tenant/workspace PostgreSQL exception queue."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import date
from typing import Any

from reconforge.infrastructure.postgres import set_local_tenant_scope, validate_tenant_id
from reconforge.infrastructure.postgres_domain import PostgresAuditEventRepository
from reconforge.io.persisted import PersistedJsonError, encode_postgres_outbox_payload
from reconforge.platform.common import PlatformError, normalize_key, normalize_text, platform_id

EXCEPTION_STATUSES = ("Open", "In Review", "Resolved", "Accepted Risk", "Closed")
RISK_RATINGS = ("low", "medium", "high", "critical")
_MAX_BULK = 1_000

POSTGRES_EXCEPTIONS_SCHEMA_SQL = r"""
CREATE TABLE IF NOT EXISTS reconforge.exception_queue_records (
 tenant_id TEXT NOT NULL,id TEXT NOT NULL,workspace_id TEXT NOT NULL,source_type TEXT NOT NULL,
 source_id TEXT NOT NULL,period_name TEXT NOT NULL DEFAULT '',entity_code TEXT NOT NULL DEFAULT '',
 account_code TEXT NOT NULL DEFAULT '',control_code TEXT NOT NULL DEFAULT '',
 risk_rating TEXT NOT NULL DEFAULT 'medium' CHECK(risk_rating IN('low','medium','high','critical')),
 owner TEXT NOT NULL DEFAULT '',status TEXT NOT NULL DEFAULT 'Open'
 CHECK(status IN('Open','In Review','Resolved','Accepted Risk','Closed')),
 escalation_level TEXT NOT NULL DEFAULT '',sla_target_date DATE,description TEXT NOT NULL,
 created_by TEXT NOT NULL,last_actor TEXT NOT NULL,created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),row_version BIGINT NOT NULL DEFAULT 1 CHECK(row_version>0),
 PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,workspace_id,source_type,source_id),
 FOREIGN KEY(tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS reconforge.exception_queue_history (
 tenant_id TEXT NOT NULL,id TEXT NOT NULL,exception_id TEXT NOT NULL,action TEXT NOT NULL,
 from_status TEXT NOT NULL,to_status TEXT NOT NULL,from_owner TEXT NOT NULL,to_owner TEXT NOT NULL,
 actor_label TEXT NOT NULL,occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 PRIMARY KEY(tenant_id,id),
 FOREIGN KEY(tenant_id,exception_id) REFERENCES reconforge.exception_queue_records(tenant_id,id) ON DELETE RESTRICT,
 CHECK(to_status IN('Open','In Review','Resolved','Accepted Risk','Closed'))
);
CREATE INDEX IF NOT EXISTS exception_queue_filter_idx ON reconforge.exception_queue_records
 (tenant_id,status,owner,period_name,entity_code,risk_rating,created_at DESC,id);
CREATE INDEX IF NOT EXISTS exception_queue_source_idx ON reconforge.exception_queue_records
 (tenant_id,workspace_id,source_type,source_id);
CREATE INDEX IF NOT EXISTS exception_queue_history_idx ON reconforge.exception_queue_history
 (tenant_id,exception_id,occurred_at,id);

CREATE OR REPLACE FUNCTION reconforge.exception_queue_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_TABLE_NAME='exception_queue_records' THEN
  IF TG_OP='UPDATE' AND (NEW.workspace_id,NEW.source_type,NEW.source_id,NEW.created_by,NEW.created_at)
   IS DISTINCT FROM (OLD.workspace_id,OLD.source_type,OLD.source_id,OLD.created_by,OLD.created_at)
  THEN RAISE EXCEPTION 'exception source identity is immutable'; END IF;
  IF TG_OP='DELETE' THEN RAISE EXCEPTION 'exception queue records are retained; update status instead'; END IF;
  RETURN NEW;
 END IF;
 IF TG_OP IN('UPDATE','DELETE') THEN RAISE EXCEPTION 'exception transition history is append-only'; END IF;
 IF NOT EXISTS(
  SELECT 1 FROM reconforge.exception_queue_records q WHERE q.tenant_id=NEW.tenant_id
   AND q.id=NEW.exception_id AND q.status=NEW.to_status AND q.owner=NEW.to_owner
 ) THEN RAISE EXCEPTION 'exception transition history must match current state'; END IF;
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS exception_queue_records_guard ON reconforge.exception_queue_records;
CREATE TRIGGER exception_queue_records_guard BEFORE UPDATE OR DELETE ON reconforge.exception_queue_records
 FOR EACH ROW EXECUTE FUNCTION reconforge.exception_queue_guard();
DROP TRIGGER IF EXISTS exception_queue_history_guard ON reconforge.exception_queue_history;
CREATE TRIGGER exception_queue_history_guard BEFORE INSERT OR UPDATE OR DELETE ON reconforge.exception_queue_history
 FOR EACH ROW EXECUTE FUNCTION reconforge.exception_queue_guard();

DO $rls$ DECLARE table_name TEXT; BEGIN
 FOREACH table_name IN ARRAY ARRAY['exception_queue_records','exception_queue_history'] LOOP
  EXECUTE format('ALTER TABLE reconforge.%I ENABLE ROW LEVEL SECURITY',table_name);
  EXECUTE format('ALTER TABLE reconforge.%I FORCE ROW LEVEL SECURITY',table_name);
  EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON reconforge.%I',table_name);
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname='reconforge' AND tablename=table_name AND policyname='tenant_scope') THEN
   EXECUTE format('CREATE POLICY tenant_isolation ON reconforge.%I USING (tenant_id=current_setting(''app.tenant_id'',true)) WITH CHECK (tenant_id=current_setting(''app.tenant_id'',true))',table_name);
  END IF;
 END LOOP;
END $rls$;
"""


class PostgresExceptionQueueError(RuntimeError):
    """Safe exception-queue persistence failure."""


def _choice(value: object, field: str, choices: tuple[str, ...]) -> str:
    raw = normalize_text(value, default="")
    for choice in choices:
        if raw.casefold() == choice.casefold():
            return choice
    raise PlatformError(f"{field} must be one of: {', '.join(choices)}.")


def _optional_date(value: object) -> str:
    raw = normalize_text(value, default="")
    if not raw:
        return ""
    try:
        parsed = date.fromisoformat(raw)
    except ValueError as exc:
        raise PlatformError("SLA target date must use YYYY-MM-DD format.") from exc
    if parsed.isoformat() != raw:
        raise PlatformError("SLA target date must use YYYY-MM-DD format.")
    return raw


def _bounded(value: object, field: str, maximum: int, *, required: bool = False) -> str:
    result = normalize_text(value, default="")
    if required and not result:
        raise PlatformError(f"{field} is required.")
    if len(result) > maximum:
        raise PlatformError(f"{field} must not exceed {maximum} characters.")
    return result


class PostgresExceptionQueueRepository:
    """Implement the complete Exception Queue Application port for one tenant."""

    def __init__(self, connection: Any, tenant_id: str) -> None:
        self.connection = connection
        self.tenant_id = validate_tenant_id(tenant_id)

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        try:
            with self.connection.transaction():
                set_local_tenant_scope(self.connection, self.tenant_id)
                yield
        except (PlatformError, PostgresExceptionQueueError):
            raise
        except Exception as exc:
            raise PostgresExceptionQueueError("PostgreSQL exception-queue operation failed.") from exc

    def _workspace_id(self, workspace: str) -> str:
        workspace_name = _bounded(workspace, "Workspace", 160, required=True)
        row = self.connection.execute(
            "SELECT id FROM reconforge.domain_workspaces WHERE tenant_id=%s AND name=%s",
            (self.tenant_id, workspace_name),
        ).fetchone()
        if row is None:
            raise PlatformError("Workspace was not found for this tenant.")
        return str(row["id"])

    def _record(self, exception_id: str, *, lock: bool = False) -> dict[str, Any]:
        query = "SELECT * FROM reconforge.exception_queue_records WHERE tenant_id=%s AND id=%s"
        if lock:
            query += " FOR UPDATE"
        row = self.connection.execute(
            query,
            (self.tenant_id, _bounded(exception_id, "Exception id", 200, required=True)),
        ).fetchone()
        if row is None:
            raise PlatformError("Exception queue record not found.")
        return dict(row)

    def _event(
        self,
        *,
        actor_label: str,
        object_id: str,
        action: str,
        version: object,
        metadata: Mapping[str, object],
    ) -> None:
        actor = normalize_text(actor_label, default="local-cli")
        audit = PostgresAuditEventRepository(self.connection, self.tenant_id).append(
            actor_label=actor,
            object_type="exception",
            object_id=object_id,
            action=action,
            metadata=dict(metadata),
        )
        payload = {
            "audit_event_id": audit.id,
            "object_type": "exception",
            "object_id": object_id,
            "action": action,
            **dict(metadata),
        }
        try:
            encoded = encode_postgres_outbox_payload(payload).text
        except PersistedJsonError as exc:
            raise PlatformError("Unable to encode exception-queue event.") from exc
        self.connection.execute(
            """INSERT INTO reconforge.outbox_events(tenant_id,event_id,event_type,aggregate_type,aggregate_id,payload)
            VALUES(%s,%s,%s,'exception',%s,CAST(%s AS jsonb))
            ON CONFLICT(tenant_id,event_id) DO NOTHING""",
            (self.tenant_id, platform_id("OBX", action, object_id, version), action, object_id, encoded),
        )

    def _history(
        self,
        *,
        before: Mapping[str, Any] | None,
        after: Mapping[str, Any],
        action: str,
        actor_label: str,
    ) -> None:
        version = after["row_version"]
        history_id = platform_id("EXH", after["id"], action, version)
        self.connection.execute(
            """INSERT INTO reconforge.exception_queue_history(
            tenant_id,id,exception_id,action,from_status,to_status,from_owner,to_owner,actor_label)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                self.tenant_id,
                history_id,
                after["id"],
                action,
                "" if before is None else before["status"],
                after["status"],
                "" if before is None else before["owner"],
                after["owner"],
                normalize_text(actor_label, default="local-cli"),
            ),
        )

    def _update(
        self,
        record: Mapping[str, Any],
        *,
        status: str | None,
        owner: str | None,
        actor_label: str,
        action: str,
    ) -> dict[str, Any]:
        selected_status = (
            str(record["status"]) if status is None else _choice(status, "Exception status", EXCEPTION_STATUSES)
        )
        selected_owner = str(record["owner"]) if owner is None else _bounded(owner, "Exception owner", 160)
        if owner is not None and not selected_owner:
            raise PlatformError("Exception owner is required.")
        row = self.connection.execute(
            """UPDATE reconforge.exception_queue_records SET status=%s,owner=%s,last_actor=%s,
            updated_at=now(),row_version=row_version+1 WHERE tenant_id=%s AND id=%s RETURNING *""",
            (
                selected_status,
                selected_owner,
                normalize_text(actor_label, default="local-cli"),
                self.tenant_id,
                record["id"],
            ),
        ).fetchone()
        if row is None:
            raise PlatformError("Exception queue record not found.")
        result = dict(row)
        self._history(before=record, after=result, action=action, actor_label=actor_label)
        return result

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
        source = normalize_key(source_type, default="")
        source_key = normalize_key(source_id, default="")
        if not source or not source_key:
            raise PlatformError("Exception source type and source id are required.")
        if len(source) > 100 or len(source_key) > 200:
            raise PlatformError("Exception source type or source id exceeds its safe length limit.")
        selected_description = _bounded(description, "Exception description", 4_000, required=True)
        selected_status = _choice(status, "Exception status", EXCEPTION_STATUSES)
        selected_risk = _choice(risk_rating, "Risk rating", RISK_RATINGS)
        selected_sla = _optional_date(sla_target_date)
        with self._transaction():
            workspace_id = self._workspace_id(workspace)
            exception_id = platform_id("EXQ", workspace_id, source, source_key)
            before_row = self.connection.execute(
                """SELECT * FROM reconforge.exception_queue_records WHERE tenant_id=%s
                AND workspace_id=%s AND source_type=%s AND source_id=%s FOR UPDATE""",
                (self.tenant_id, workspace_id, source, source_key),
            ).fetchone()
            before = None if before_row is None else dict(before_row)
            row = self.connection.execute(
                """INSERT INTO reconforge.exception_queue_records(
                tenant_id,id,workspace_id,source_type,source_id,period_name,entity_code,account_code,
                control_code,risk_rating,owner,status,escalation_level,sla_target_date,description,
                created_by,last_actor) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NULLIF(%s,'')::date,%s,%s,%s)
                ON CONFLICT(tenant_id,workspace_id,source_type,source_id) DO UPDATE SET
                period_name=EXCLUDED.period_name,entity_code=EXCLUDED.entity_code,
                account_code=EXCLUDED.account_code,control_code=EXCLUDED.control_code,
                risk_rating=EXCLUDED.risk_rating,owner=EXCLUDED.owner,status=EXCLUDED.status,
                escalation_level=EXCLUDED.escalation_level,sla_target_date=EXCLUDED.sla_target_date,
                description=EXCLUDED.description,last_actor=EXCLUDED.last_actor,updated_at=now(),
                row_version=reconforge.exception_queue_records.row_version+1 RETURNING *""",
                (
                    self.tenant_id,
                    exception_id,
                    workspace_id,
                    source,
                    source_key,
                    _bounded(period_name, "Period", 64),
                    _bounded(entity_code, "Entity code", 160),
                    _bounded(account_code, "Account code", 160),
                    _bounded(control_code, "Control code", 160),
                    selected_risk,
                    _bounded(owner, "Exception owner", 160),
                    selected_status,
                    _bounded(escalation_level, "Escalation level", 64),
                    selected_sla,
                    selected_description,
                    _bounded(actor_label, "Actor label", 160, required=True),
                    normalize_text(actor_label, default="local-cli"),
                ),
            ).fetchone()
            if row is None:
                raise PlatformError("Unable to save exception queue record.")
            result = dict(row)
            self._history(before=before, after=result, action="exception_saved", actor_label=actor_label)
            self._event(
                actor_label=actor_label,
                object_id=exception_id,
                action="exception_saved",
                version=result["row_version"],
                metadata={
                    "source_type": source,
                    "source_id": source_key,
                    "risk_rating": selected_risk,
                    "status": selected_status,
                },
            )
            return result

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
        selected_risk = "" if not risk_rating else _choice(risk_rating, "Risk rating", RISK_RATINGS)
        selected_status = "" if not status else _choice(status, "Exception status", EXCEPTION_STATUSES)
        filters = (
            _bounded(period_name, "Period", 64),
            _bounded(entity_code, "Entity code", 160),
            _bounded(account_code, "Account code", 160),
            _bounded(control_code, "Control code", 160),
        )
        with self._transaction():
            rows = self.connection.execute(
                """SELECT * FROM reconforge.exception_queue_records WHERE tenant_id=%s
                AND (%s='' OR period_name=%s) AND (%s='' OR entity_code=%s)
                AND (%s='' OR account_code=%s) AND (%s='' OR control_code=%s)
                AND (%s='' OR risk_rating=%s) AND (%s='' OR owner=%s) AND (%s='' OR status=%s)
                ORDER BY CASE risk_rating WHEN 'critical' THEN 4 WHEN 'high' THEN 3
                WHEN 'medium' THEN 2 ELSE 1 END DESC,created_at DESC,id LIMIT 10000""",
                (
                    self.tenant_id,
                    filters[0],
                    filters[0],
                    filters[1],
                    filters[1],
                    filters[2],
                    filters[2],
                    filters[3],
                    filters[3],
                    selected_risk,
                    selected_risk,
                    _bounded(owner, "Exception owner", 160),
                    _bounded(owner, "Exception owner", 160),
                    selected_status,
                    selected_status,
                ),
            ).fetchall()
            return [dict(row) for row in rows]

    def assign(self, exception_id: str, *, owner: str, actor_label: str = "local-cli") -> dict[str, Any]:
        with self._transaction():
            before = self._record(exception_id, lock=True)
            result = self._update(
                before,
                status=None,
                owner=owner,
                actor_label=actor_label,
                action="exception_assigned",
            )
            self._event(
                actor_label=actor_label,
                object_id=str(result["id"]),
                action="exception_assigned",
                version=result["row_version"],
                metadata={"owner": result["owner"]},
            )
            return result

    def set_status(
        self,
        exception_id: str,
        *,
        status: str,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        with self._transaction():
            before = self._record(exception_id, lock=True)
            result = self._update(
                before,
                status=status,
                owner=None,
                actor_label=actor_label,
                action="exception_status_updated",
            )
            self._event(
                actor_label=actor_label,
                object_id=str(result["id"]),
                action="exception_status_updated",
                version=result["row_version"],
                metadata={"status": result["status"]},
            )
            return result

    def bulk_update(
        self,
        exception_ids: Sequence[str],
        *,
        status: str = "",
        owner: str = "",
        actor_label: str = "local-cli",
    ) -> int:
        if not status and not owner:
            raise PlatformError("Bulk update requires status or owner.")
        if isinstance(exception_ids, (str, bytes)):
            raise PlatformError("Bulk update requires a sequence of exception identifiers, not text.")
        selected_status = None if not status else _choice(status, "Exception status", EXCEPTION_STATUSES)
        selected_owner = None if not owner else _bounded(owner, "Exception owner", 160)
        identifiers = tuple(dict.fromkeys(_bounded(item, "Exception id", 200) for item in exception_ids))
        if not identifiers or any(not item for item in identifiers):
            raise PlatformError("Bulk update requires valid exception identifiers.")
        if len(identifiers) > _MAX_BULK:
            raise PlatformError("Bulk update is limited to 1000 unique exceptions.")
        with self._transaction():
            records = [self._record(identifier, lock=True) for identifier in sorted(identifiers)]
            results = []
            for before in records:
                results.append(
                    self._update(
                        before,
                        status=selected_status,
                        owner=selected_owner,
                        actor_label=actor_label,
                        action="exception_bulk_updated",
                    )
                )
            self._event(
                actor_label=actor_label,
                object_id="bulk",
                action="exception_bulk_updated",
                version=platform_id("BULK", *(f"{row['id']}:{row['row_version']}" for row in results)),
                metadata={"count": len(records), "status": selected_status or "", "owner": selected_owner or ""},
            )
            return len(records)

    def get(self, exception_id: str) -> dict[str, Any]:
        with self._transaction():
            result = self._record(exception_id)
            history = self.connection.execute(
                """SELECT * FROM reconforge.exception_queue_history WHERE tenant_id=%s
                AND exception_id=%s ORDER BY occurred_at,id LIMIT 10000""",
                (self.tenant_id, result["id"]),
            ).fetchall()
            result["history"] = [dict(row) for row in history]
            return result
