"""Tenant-scoped PostgreSQL approval and certification metadata."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any

from reconforge.auth.rbac import same_actor
from reconforge.infrastructure.postgres import set_local_tenant_scope, validate_tenant_id
from reconforge.infrastructure.postgres_domain import PostgresAuditEventRepository
from reconforge.io.persisted import PersistedJsonError, encode_postgres_outbox_payload
from reconforge.platform.common import PlatformError, normalize_key, normalize_text, platform_id

POSTGRES_APPROVALS_SCHEMA_SQL = r"""
CREATE TABLE IF NOT EXISTS reconforge.approval_requests (
 tenant_id TEXT NOT NULL,id TEXT NOT NULL,object_type TEXT NOT NULL,object_id TEXT NOT NULL,
 title TEXT NOT NULL,requested_by TEXT NOT NULL,assigned_to TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'Submitted' CHECK(status IN('Submitted','Approved','Rejected')),
 reason TEXT NOT NULL DEFAULT '',decision_reason TEXT NOT NULL DEFAULT '',
 override_reason TEXT NOT NULL DEFAULT '',decided_by TEXT NOT NULL DEFAULT '',
 decided_at TIMESTAMPTZ,created_by TEXT NOT NULL,created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),row_version BIGINT NOT NULL DEFAULT 1 CHECK(row_version>0),
 PRIMARY KEY(tenant_id,id)
);
CREATE TABLE IF NOT EXISTS reconforge.certification_records (
 tenant_id TEXT NOT NULL,id TEXT NOT NULL,object_type TEXT NOT NULL,object_id TEXT NOT NULL,
 period_name TEXT NOT NULL DEFAULT '',entity_code TEXT NOT NULL DEFAULT '',
 status TEXT NOT NULL CHECK(status IN('Prepared','Reviewed')),prepared_by TEXT NOT NULL,
 reviewed_by TEXT NOT NULL DEFAULT '',note TEXT NOT NULL DEFAULT '',created_by TEXT NOT NULL,
 prepared_at TIMESTAMPTZ NOT NULL DEFAULT now(),reviewed_at TIMESTAMPTZ,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 row_version BIGINT NOT NULL DEFAULT 1 CHECK(row_version>0),PRIMARY KEY(tenant_id,id),
 UNIQUE(tenant_id,object_type,object_id)
);
CREATE INDEX IF NOT EXISTS approval_requests_queue_idx ON reconforge.approval_requests
 (tenant_id,status,assigned_to,created_at,id);
CREATE INDEX IF NOT EXISTS certification_records_queue_idx ON reconforge.certification_records
 (tenant_id,status,period_name,entity_code,updated_at,id);

CREATE OR REPLACE FUNCTION reconforge.approval_request_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='INSERT' AND (NEW.status<>'Submitted' OR NEW.requested_by='' OR NEW.assigned_to='' OR NEW.decided_by<>'' OR NEW.decided_at IS NOT NULL OR NEW.override_reason<>'') THEN RAISE EXCEPTION 'approval requests require complete Submitted metadata'; END IF;
 IF TG_OP='UPDATE' AND OLD.status<>'Submitted' THEN RAISE EXCEPTION 'decided approval requests are immutable'; END IF;
 IF TG_OP='UPDATE' AND NEW.status NOT IN('Approved','Rejected') THEN RAISE EXCEPTION 'approval requests can only be approved or rejected'; END IF;
 IF TG_OP='UPDATE' AND (NEW.object_type,NEW.object_id,NEW.title,NEW.requested_by,NEW.assigned_to,NEW.reason,NEW.created_by,NEW.created_at) IS DISTINCT FROM (OLD.object_type,OLD.object_id,OLD.title,OLD.requested_by,OLD.assigned_to,OLD.reason,OLD.created_by,OLD.created_at) THEN RAISE EXCEPTION 'approval request submission evidence is immutable'; END IF;
 IF TG_OP='UPDATE' AND (NEW.decided_by='' OR NEW.decided_at IS NULL OR NEW.override_reason<>'' OR (NEW.status='Approved' AND lower(trim(NEW.decided_by))=lower(trim(OLD.requested_by))) OR (NEW.status='Rejected' AND NEW.decision_reason='')) THEN RAISE EXCEPTION 'approval decisions require maker checker no override and rejection reason'; END IF;
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'approval request history is immutable'; END IF;
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS approval_requests_guard ON reconforge.approval_requests;
CREATE TRIGGER approval_requests_guard BEFORE INSERT OR UPDATE OR DELETE ON reconforge.approval_requests FOR EACH ROW EXECUTE FUNCTION reconforge.approval_request_guard();

CREATE OR REPLACE FUNCTION reconforge.certification_record_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='INSERT' AND (NEW.status<>'Prepared' OR NEW.prepared_by='' OR NEW.reviewed_by<>'' OR NEW.reviewed_at IS NOT NULL) THEN RAISE EXCEPTION 'certification metadata must be prepared before review'; END IF;
 IF TG_OP='UPDATE' AND OLD.status='Reviewed' THEN RAISE EXCEPTION 'reviewed certification metadata is immutable'; END IF;
 IF TG_OP='UPDATE' AND (NEW.object_type,NEW.object_id,NEW.period_name,NEW.entity_code,NEW.prepared_by,NEW.prepared_at,NEW.created_by,NEW.created_at) IS DISTINCT FROM (OLD.object_type,OLD.object_id,OLD.period_name,OLD.entity_code,OLD.prepared_by,OLD.prepared_at,OLD.created_by,OLD.created_at) THEN RAISE EXCEPTION 'prepared certification scope and preparer evidence are immutable'; END IF;
 IF TG_OP='UPDATE' AND (NEW.status<>'Reviewed' OR NEW.reviewed_by='' OR NEW.reviewed_at IS NULL OR lower(trim(NEW.reviewed_by))=lower(trim(OLD.prepared_by))) THEN RAISE EXCEPTION 'certification review requires separation of duties'; END IF;
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'certification metadata history is immutable'; END IF;
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS certification_records_guard ON reconforge.certification_records;
CREATE TRIGGER certification_records_guard BEFORE INSERT OR UPDATE OR DELETE ON reconforge.certification_records FOR EACH ROW EXECUTE FUNCTION reconforge.certification_record_guard();

DO $rls$ DECLARE table_name TEXT; BEGIN
 FOREACH table_name IN ARRAY ARRAY['approval_requests','certification_records'] LOOP
  EXECUTE format('ALTER TABLE reconforge.%I ENABLE ROW LEVEL SECURITY',table_name); EXECUTE format('ALTER TABLE reconforge.%I FORCE ROW LEVEL SECURITY',table_name);
  EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON reconforge.%I',table_name);
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname='reconforge' AND tablename=table_name AND policyname='tenant_scope') THEN
   EXECUTE format('CREATE POLICY tenant_isolation ON reconforge.%I USING (tenant_id=current_setting(''app.tenant_id'',true)) WITH CHECK (tenant_id=current_setting(''app.tenant_id'',true))',table_name);
  END IF;
 END LOOP;
END $rls$;
"""


class PostgresApprovalsError(RuntimeError):
    """Safe PostgreSQL approval persistence failure."""


class PostgresApprovalRepository:
    """Implement the complete approval Application port for one tenant."""

    def __init__(self, connection: Any, tenant_id: str) -> None:
        self.connection = connection
        self.tenant_id = validate_tenant_id(tenant_id)

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        try:
            with self.connection.transaction():
                set_local_tenant_scope(self.connection, self.tenant_id)
                yield
        except (PlatformError, PostgresApprovalsError):
            raise
        except Exception as exc:
            raise PostgresApprovalsError("PostgreSQL approval operation failed.") from exc

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
            raise PlatformError("Unable to encode approval evidence.") from exc
        self.connection.execute(
            """INSERT INTO reconforge.outbox_events(tenant_id,event_id,event_type,aggregate_type,aggregate_id,payload)
            VALUES(%s,%s,%s,%s,%s,CAST(%s AS jsonb)) ON CONFLICT(tenant_id,event_id) DO NOTHING""",
            (self.tenant_id, event_id, action, object_type, object_id, payload),
        )

    def _request(self, approval_id: str, *, lock: bool = False) -> dict[str, Any]:
        query = (
            "SELECT * FROM reconforge.approval_requests WHERE tenant_id=%s AND id=%s FOR UPDATE"
            if lock
            else "SELECT * FROM reconforge.approval_requests WHERE tenant_id=%s AND id=%s"
        )
        row = self.connection.execute(query, (self.tenant_id, normalize_text(approval_id, default=""))).fetchone()
        if row is None:
            raise PlatformError("Approval request not found.")
        return dict(row)

    def _certification(self, object_type: object, object_id: object, *, lock: bool = False) -> dict[str, Any]:
        target_type = normalize_key(object_type, default="")
        target_id = normalize_key(object_id, default="")
        query = (
            "SELECT * FROM reconforge.certification_records WHERE tenant_id=%s AND object_type=%s AND object_id=%s FOR UPDATE"
            if lock
            else "SELECT * FROM reconforge.certification_records WHERE tenant_id=%s AND object_type=%s AND object_id=%s"
        )
        row = self.connection.execute(query, (self.tenant_id, target_type, target_id)).fetchone()
        if row is None:
            raise PlatformError("Certification metadata not found.")
        return dict(row)

    def submit(
        self,
        *,
        object_type: str,
        object_id: str,
        title: str,
        assigned_to: str,
        requested_by: str = "",
        reason: str = "",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        target_type = normalize_key(object_type, default="")
        target_id = normalize_key(object_id, default="")
        if not target_type or not target_id:
            raise PlatformError("Approval object type and id are required.")
        requester = normalize_text(requested_by, default=actor_label)
        assignee = normalize_text(assigned_to, default="")
        if not assignee:
            raise PlatformError("Approval assignee is required.")
        request_title = normalize_text(title, default=f"{target_type} approval")
        approval_id = platform_id("APR", target_type, target_id, request_title, assignee)
        with self._transaction():
            row = self.connection.execute(
                """INSERT INTO reconforge.approval_requests(
                tenant_id,id,object_type,object_id,title,requested_by,assigned_to,status,reason,created_by)
                VALUES(%s,%s,%s,%s,%s,%s,%s,'Submitted',%s,%s)
                ON CONFLICT(tenant_id,id) DO NOTHING RETURNING row_version""",
                (
                    self.tenant_id,
                    approval_id,
                    target_type,
                    target_id,
                    request_title,
                    requester,
                    assignee,
                    normalize_text(reason, default=""),
                    normalize_text(actor_label, default="local-cli"),
                ),
            ).fetchone()
            if row is None:
                raise PlatformError("An approval request with this identity already exists and is immutable.")
            self._event(
                actor_label=actor_label,
                object_type="approval_request",
                object_id=approval_id,
                action="approval_submitted",
                version=row["row_version"],
                metadata={"target_type": target_type, "target_id": target_id, "assigned_to": assignee},
            )
            return self._request(approval_id)

    def _decide(
        self,
        approval_id: str,
        *,
        status: str,
        actor_label: str,
        reason: str,
        override_reason: str,
    ) -> dict[str, Any]:
        actor = normalize_text(actor_label, default="local-cli")
        decision_reason = normalize_text(reason, default="")
        if override_reason.strip():
            raise PlatformError("Approval SoD overrides are not permitted.")
        if status == "Rejected" and not decision_reason:
            raise PlatformError("Rejection reason is required.")
        request = self._request(approval_id, lock=True)
        if request["status"] != "Submitted":
            raise PlatformError("Only Submitted approval requests can be decided.")
        if status == "Approved" and same_actor(request["requested_by"], actor):
            raise PlatformError("Separation of duties conflict: requester cannot approve their own request.")
        row = self.connection.execute(
            """UPDATE reconforge.approval_requests SET status=%s,decision_reason=%s,
            override_reason='',decided_by=%s,decided_at=now(),updated_at=now(),row_version=row_version+1
            WHERE tenant_id=%s AND id=%s AND status='Submitted' RETURNING row_version""",
            (status, decision_reason, actor, self.tenant_id, approval_id),
        ).fetchone()
        if row is None:
            raise PlatformError("Approval request changed concurrently; reload and retry.")
        self._event(
            actor_label=actor,
            object_type="approval_request",
            object_id=approval_id,
            action=f"approval_{status.lower()}",
            version=row["row_version"],
            metadata={"status": status, "override_used": False, "reason_required": status == "Rejected"},
        )
        return self._request(approval_id)

    def approve(
        self,
        approval_id: str,
        *,
        actor_label: str = "local-cli",
        reason: str = "",
        override_reason: str = "",
    ) -> dict[str, Any]:
        with self._transaction():
            return self._decide(
                approval_id,
                status="Approved",
                actor_label=actor_label,
                reason=reason,
                override_reason=override_reason,
            )

    def reject(self, approval_id: str, *, actor_label: str = "local-cli", reason: str) -> dict[str, Any]:
        with self._transaction():
            return self._decide(
                approval_id,
                status="Rejected",
                actor_label=actor_label,
                reason=reason,
                override_reason="",
            )

    def prepare_certification(
        self,
        *,
        object_type: str,
        object_id: str,
        period_name: str = "",
        entity_code: str = "",
        note: str = "",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        target_type = normalize_key(object_type, default="")
        target_id = normalize_key(object_id, default="")
        if not target_type or not target_id:
            raise PlatformError("Certification object type and id are required.")
        certification_id = platform_id("CERT", target_type, target_id)
        actor = normalize_text(actor_label, default="local-cli")
        with self._transaction():
            row = self.connection.execute(
                """INSERT INTO reconforge.certification_records(
                tenant_id,id,object_type,object_id,period_name,entity_code,status,prepared_by,note,created_by)
                VALUES(%s,%s,%s,%s,%s,%s,'Prepared',%s,%s,%s)
                ON CONFLICT(tenant_id,object_type,object_id) DO NOTHING RETURNING row_version""",
                (
                    self.tenant_id,
                    certification_id,
                    target_type,
                    target_id,
                    normalize_key(period_name, default=""),
                    normalize_key(entity_code, default=""),
                    actor,
                    normalize_text(note, default=""),
                    actor,
                ),
            ).fetchone()
            if row is None:
                raise PlatformError("Certification metadata already exists and cannot be silently replaced.")
            self._event(
                actor_label=actor,
                object_type="certification_metadata",
                object_id=certification_id,
                action="certification_prepared",
                version=row["row_version"],
                metadata={"target_type": target_type, "target_id": target_id, "status": "Prepared"},
            )
            return self._certification(target_type, target_id)

    def review_certification(
        self,
        *,
        object_type: str,
        object_id: str,
        note: str = "",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        actor = normalize_text(actor_label, default="local-cli")
        with self._transaction():
            current = self._certification(object_type, object_id, lock=True)
            if current["status"] != "Prepared":
                raise PlatformError("Only Prepared certification metadata can be reviewed.")
            if same_actor(current["prepared_by"], actor):
                raise PlatformError("Separation of duties conflict: preparer and reviewer must be different.")
            row = self.connection.execute(
                """UPDATE reconforge.certification_records SET status='Reviewed',reviewed_by=%s,
                reviewed_at=now(),note=%s,updated_at=now(),row_version=row_version+1
                WHERE tenant_id=%s AND id=%s AND status='Prepared' RETURNING row_version""",
                (actor, normalize_text(note, default=str(current["note"])), self.tenant_id, current["id"]),
            ).fetchone()
            if row is None:
                raise PlatformError("Certification metadata changed concurrently; reload and retry.")
            self._event(
                actor_label=actor,
                object_type="certification_metadata",
                object_id=str(current["id"]),
                action="certification_reviewed",
                version=row["row_version"],
                metadata={
                    "target_type": current["object_type"],
                    "target_id": current["object_id"],
                    "status": "Reviewed",
                },
            )
            return self._certification(current["object_type"], current["object_id"])

    def list_requests(self, *, status: str = "") -> list[dict[str, Any]]:
        selected = normalize_text(status, default="")
        if selected and selected not in {"Submitted", "Approved", "Rejected"}:
            raise PlatformError("Unsupported approval request status.")
        with self._transaction():
            return [
                dict(row)
                for row in self.connection.execute(
                    """SELECT * FROM reconforge.approval_requests WHERE tenant_id=%s
                AND (%s='' OR status=%s) ORDER BY created_at DESC,id DESC LIMIT 10000""",
                    (self.tenant_id, selected, selected),
                ).fetchall()
            ]

    def list_certifications(self) -> list[dict[str, Any]]:
        with self._transaction():
            return [
                dict(row)
                for row in self.connection.execute(
                    "SELECT * FROM reconforge.certification_records WHERE tenant_id=%s ORDER BY updated_at DESC,id DESC LIMIT 10000",
                    (self.tenant_id,),
                ).fetchall()
            ]

    def get(self, approval_id: str) -> dict[str, Any]:
        with self._transaction():
            return self._request(approval_id)
