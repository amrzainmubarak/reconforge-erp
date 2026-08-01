"""PostgreSQL aggregate for governed inventory counts and reorder controls."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any

from reconforge.application.inventory_planning import InventoryPlanningSummary
from reconforge.auth.rbac import same_actor
from reconforge.infrastructure.postgres import set_local_tenant_scope, validate_tenant_id
from reconforge.infrastructure.postgres_domain import PostgresAuditEventRepository
from reconforge.io.persisted import PersistedJsonError, encode_postgres_outbox_payload
from reconforge.platform.common import PlatformError, platform_id
from reconforge.platform.inventory_values import (
    MAX_LIST_LIMIT,
    choice,
    clean_text,
    code,
    document_number,
    iso_date,
    page,
    public_record,
    quantity_to_scaled,
    scaled_to_text,
)
from reconforge.utils.time import utc_now_text

POSTGRES_INVENTORY_PLANNING_SCHEMA_SQL = r"""
CREATE TABLE IF NOT EXISTS reconforge.inventory_count_sessions (
 tenant_id TEXT NOT NULL,id TEXT NOT NULL,workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,
 legal_entity_id TEXT NOT NULL,period_id TEXT NOT NULL,location_id TEXT NOT NULL,count_number TEXT NOT NULL,
 count_date DATE NOT NULL,description TEXT NOT NULL DEFAULT '',status TEXT NOT NULL DEFAULT 'Draft'
 CHECK(status IN('Draft','Counting','Submitted','Approved','Cancelled')),created_by TEXT NOT NULL,
 started_by TEXT NOT NULL DEFAULT '',started_at TIMESTAMPTZ,submitted_by TEXT NOT NULL DEFAULT '',
 submitted_at TIMESTAMPTZ,submit_reason TEXT NOT NULL DEFAULT '',approved_by TEXT NOT NULL DEFAULT '',
 approved_at TIMESTAMPTZ,approval_reason TEXT NOT NULL DEFAULT '',cancelled_by TEXT NOT NULL DEFAULT '',
 cancelled_at TIMESTAMPTZ,cancel_reason TEXT NOT NULL DEFAULT '',adjustment_movement_id TEXT,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 row_version BIGINT NOT NULL DEFAULT 1 CHECK(row_version>0),PRIMARY KEY(tenant_id,id),
 UNIQUE(tenant_id,workspace_id,count_number),UNIQUE(tenant_id,adjustment_movement_id),
 FOREIGN KEY(tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id) ON DELETE CASCADE,
 FOREIGN KEY(tenant_id,organization_id) REFERENCES reconforge.organizations(tenant_id,id) ON DELETE RESTRICT,
 FOREIGN KEY(tenant_id,legal_entity_id) REFERENCES reconforge.legal_entities(tenant_id,id) ON DELETE RESTRICT,
 FOREIGN KEY(tenant_id,period_id) REFERENCES reconforge.fiscal_periods(tenant_id,id) ON DELETE RESTRICT,
 FOREIGN KEY(tenant_id,location_id) REFERENCES reconforge.inventory_locations(tenant_id,id) ON DELETE RESTRICT,
 FOREIGN KEY(tenant_id,adjustment_movement_id) REFERENCES reconforge.inventory_movements(tenant_id,id) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS reconforge.inventory_count_lines (
 tenant_id TEXT NOT NULL,id TEXT NOT NULL,session_id TEXT NOT NULL,line_number INTEGER NOT NULL CHECK(line_number>0),
 item_id TEXT NOT NULL,uom_id TEXT NOT NULL,inventory_lot_id TEXT,expected_quantity_scaled BIGINT NOT NULL,
 counted_quantity_scaled BIGINT CHECK(counted_quantity_scaled IS NULL OR counted_quantity_scaled>=0),
 quantity_precision INTEGER NOT NULL CHECK(quantity_precision BETWEEN 0 AND 6),count_note TEXT NOT NULL DEFAULT '',
 counted_by TEXT NOT NULL DEFAULT '',counted_at TIMESTAMPTZ,created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 row_version BIGINT NOT NULL DEFAULT 1 CHECK(row_version>0),PRIMARY KEY(tenant_id,id),
 UNIQUE(tenant_id,session_id,line_number),
 FOREIGN KEY(tenant_id,session_id) REFERENCES reconforge.inventory_count_sessions(tenant_id,id) ON DELETE CASCADE,
 FOREIGN KEY(tenant_id,item_id) REFERENCES reconforge.inventory_items(tenant_id,id) ON DELETE RESTRICT,
 FOREIGN KEY(tenant_id,uom_id) REFERENCES reconforge.inventory_units_of_measure(tenant_id,id) ON DELETE RESTRICT,
 FOREIGN KEY(tenant_id,inventory_lot_id) REFERENCES reconforge.inventory_lots(tenant_id,id) ON DELETE RESTRICT
);
CREATE UNIQUE INDEX IF NOT EXISTS inventory_count_lines_item_lot_idx
 ON reconforge.inventory_count_lines(tenant_id,session_id,item_id,COALESCE(inventory_lot_id,''));
CREATE TABLE IF NOT EXISTS reconforge.inventory_reorder_rules (
 tenant_id TEXT NOT NULL,id TEXT NOT NULL,workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,
 legal_entity_id TEXT NOT NULL,item_id TEXT NOT NULL,location_id TEXT NOT NULL,
 minimum_quantity_scaled BIGINT NOT NULL CHECK(minimum_quantity_scaled>=0),
 target_quantity_scaled BIGINT NOT NULL CHECK(target_quantity_scaled>minimum_quantity_scaled),
 quantity_precision INTEGER NOT NULL CHECK(quantity_precision BETWEEN 0 AND 6),
 lead_time_days INTEGER NOT NULL DEFAULT 0 CHECK(lead_time_days BETWEEN 0 AND 3650),active BOOLEAN NOT NULL DEFAULT TRUE,
 created_by TEXT NOT NULL,created_at TIMESTAMPTZ NOT NULL DEFAULT now(),updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 row_version BIGINT NOT NULL DEFAULT 1 CHECK(row_version>0),PRIMARY KEY(tenant_id,id),
 UNIQUE(tenant_id,workspace_id,organization_id,legal_entity_id,item_id,location_id),
 FOREIGN KEY(tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id) ON DELETE CASCADE,
 FOREIGN KEY(tenant_id,organization_id) REFERENCES reconforge.organizations(tenant_id,id) ON DELETE RESTRICT,
 FOREIGN KEY(tenant_id,legal_entity_id) REFERENCES reconforge.legal_entities(tenant_id,id) ON DELETE RESTRICT,
 FOREIGN KEY(tenant_id,item_id) REFERENCES reconforge.inventory_items(tenant_id,id) ON DELETE RESTRICT,
 FOREIGN KEY(tenant_id,location_id) REFERENCES reconforge.inventory_locations(tenant_id,id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS inventory_count_sessions_scope_idx
 ON reconforge.inventory_count_sessions(tenant_id,workspace_id,organization_id,legal_entity_id,status,count_date,id);
CREATE INDEX IF NOT EXISTS inventory_count_lines_session_idx
 ON reconforge.inventory_count_lines(tenant_id,session_id,line_number,id);
CREATE INDEX IF NOT EXISTS inventory_reorder_rules_scope_idx
 ON reconforge.inventory_reorder_rules(tenant_id,workspace_id,organization_id,legal_entity_id,active,item_id,location_id);

CREATE OR REPLACE FUNCTION reconforge.inventory_count_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE session_status TEXT;
BEGIN
 IF TG_TABLE_NAME='inventory_count_sessions' THEN
  IF TG_OP='INSERT' AND NEW.status<>'Draft' THEN RAISE EXCEPTION 'inventory counts must be created as Draft'; END IF;
  IF TG_OP='UPDATE' AND NEW.status<>OLD.status AND NOT ((OLD.status='Draft' AND NEW.status IN('Counting','Cancelled')) OR (OLD.status='Counting' AND NEW.status IN('Submitted','Cancelled')) OR (OLD.status='Submitted' AND NEW.status IN('Approved','Cancelled'))) THEN RAISE EXCEPTION 'invalid inventory count status transition'; END IF;
  IF TG_OP='UPDATE' AND OLD.status='Draft' AND NEW.status='Counting' AND (NEW.started_by='' OR NEW.started_at IS NULL OR NOT EXISTS(SELECT 1 FROM reconforge.inventory_count_lines l WHERE l.tenant_id=OLD.tenant_id AND l.session_id=OLD.id)) THEN RAISE EXCEPTION 'starting an inventory count requires snapshot lines and actor metadata'; END IF;
  IF TG_OP='UPDATE' AND OLD.status='Counting' AND NEW.status='Submitted' AND (NEW.submitted_by='' OR NEW.submitted_at IS NULL OR NEW.submit_reason='' OR EXISTS(SELECT 1 FROM reconforge.inventory_count_lines l WHERE l.tenant_id=OLD.tenant_id AND l.session_id=OLD.id AND l.counted_quantity_scaled IS NULL)) THEN RAISE EXCEPTION 'submitting an inventory count requires completed lines and review metadata'; END IF;
  IF TG_OP='UPDATE' AND OLD.status='Submitted' AND NEW.status='Approved' AND (NEW.approved_by='' OR NEW.approved_at IS NULL OR NEW.approval_reason='' OR NEW.approved_by IN(OLD.created_by,OLD.submitted_by) OR
   (EXISTS(SELECT 1 FROM reconforge.inventory_count_lines l WHERE l.tenant_id=OLD.tenant_id AND l.session_id=OLD.id AND l.counted_quantity_scaled<>l.expected_quantity_scaled) AND (
    NOT EXISTS(SELECT 1 FROM reconforge.inventory_movements m WHERE m.tenant_id=OLD.tenant_id AND m.id=NEW.adjustment_movement_id AND m.status='Draft' AND m.movement_type='Adjustment' AND m.source_reference=OLD.id AND m.workspace_id=OLD.workspace_id AND m.organization_id=OLD.organization_id AND m.legal_entity_id=OLD.legal_entity_id AND m.period_id=OLD.period_id AND m.movement_date=OLD.count_date) OR
    EXISTS(SELECT 1 FROM reconforge.inventory_count_lines l WHERE l.tenant_id=OLD.tenant_id AND l.session_id=OLD.id AND l.counted_quantity_scaled<>l.expected_quantity_scaled AND NOT EXISTS(SELECT 1 FROM reconforge.inventory_movement_lines ml WHERE ml.tenant_id=l.tenant_id AND ml.movement_id=NEW.adjustment_movement_id AND ml.item_id=l.item_id AND ml.uom_id=l.uom_id AND ml.inventory_lot_id IS NOT DISTINCT FROM l.inventory_lot_id AND ml.quantity_precision=l.quantity_precision AND ml.quantity_scaled=ABS(l.counted_quantity_scaled-l.expected_quantity_scaled) AND ((l.counted_quantity_scaled<l.expected_quantity_scaled AND ml.from_location_id=OLD.location_id AND ml.to_location_id IS NULL) OR (l.counted_quantity_scaled>l.expected_quantity_scaled AND ml.to_location_id=OLD.location_id AND ml.from_location_id IS NULL)))) OR
    (SELECT COUNT(*) FROM reconforge.inventory_movement_lines ml WHERE ml.tenant_id=OLD.tenant_id AND ml.movement_id=NEW.adjustment_movement_id)<>(SELECT COUNT(*) FROM reconforge.inventory_count_lines l WHERE l.tenant_id=OLD.tenant_id AND l.session_id=OLD.id AND l.counted_quantity_scaled<>l.expected_quantity_scaled)
   )) OR
   (NOT EXISTS(SELECT 1 FROM reconforge.inventory_count_lines l WHERE l.tenant_id=OLD.tenant_id AND l.session_id=OLD.id AND l.counted_quantity_scaled<>l.expected_quantity_scaled) AND NEW.adjustment_movement_id IS NOT NULL)
  ) THEN RAISE EXCEPTION 'approving an inventory count requires maker checker and exact Draft adjustment evidence'; END IF;
  IF TG_OP='UPDATE' AND NEW.status='Cancelled' AND OLD.status<>'Cancelled' AND (NEW.cancelled_by='' OR NEW.cancelled_at IS NULL OR NEW.cancel_reason='') THEN RAISE EXCEPTION 'cancelling an inventory count requires actor timestamp and reason'; END IF;
  IF TG_OP='UPDATE' AND OLD.status<>'Draft' AND (NEW.workspace_id,NEW.organization_id,NEW.legal_entity_id,NEW.period_id,NEW.location_id,NEW.count_number,NEW.count_date,NEW.description,NEW.created_by,NEW.created_at,NEW.started_by,NEW.started_at) IS DISTINCT FROM (OLD.workspace_id,OLD.organization_id,OLD.legal_entity_id,OLD.period_id,OLD.location_id,OLD.count_number,OLD.count_date,OLD.description,OLD.created_by,OLD.created_at,OLD.started_by,OLD.started_at) THEN RAISE EXCEPTION 'started inventory count headers and start evidence are immutable'; END IF;
  IF TG_OP='UPDATE' AND OLD.status IN('Submitted','Approved','Cancelled') AND (NEW.submitted_by,NEW.submitted_at,NEW.submit_reason) IS DISTINCT FROM (OLD.submitted_by,OLD.submitted_at,OLD.submit_reason) THEN RAISE EXCEPTION 'inventory count submission metadata is immutable'; END IF;
  IF TG_OP='UPDATE' AND OLD.status IN('Approved','Cancelled') AND (NEW.approved_by,NEW.approved_at,NEW.approval_reason,NEW.adjustment_movement_id,NEW.cancelled_by,NEW.cancelled_at,NEW.cancel_reason) IS DISTINCT FROM (OLD.approved_by,OLD.approved_at,OLD.approval_reason,OLD.adjustment_movement_id,OLD.cancelled_by,OLD.cancelled_at,OLD.cancel_reason) THEN RAISE EXCEPTION 'final inventory count metadata is immutable'; END IF;
  IF TG_OP='DELETE' AND OLD.status<>'Draft' THEN RAISE EXCEPTION 'started inventory counts cannot be deleted'; END IF;
  IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;
 END IF;
 IF TG_OP='DELETE' THEN SELECT status INTO session_status FROM reconforge.inventory_count_sessions WHERE tenant_id=OLD.tenant_id AND id=OLD.session_id; ELSE SELECT status INTO session_status FROM reconforge.inventory_count_sessions WHERE tenant_id=NEW.tenant_id AND id=NEW.session_id; END IF;
 IF TG_OP='INSERT' AND (session_status<>'Draft' OR NEW.counted_quantity_scaled IS NOT NULL OR NEW.count_note<>'' OR NEW.counted_by<>'' OR NEW.counted_at IS NOT NULL) THEN RAISE EXCEPTION 'inventory count snapshot lines require a Draft session and empty results'; END IF;
 IF TG_OP='UPDATE' AND (NEW.session_id,NEW.line_number,NEW.item_id,NEW.uom_id,NEW.inventory_lot_id,NEW.expected_quantity_scaled,NEW.quantity_precision,NEW.created_at) IS DISTINCT FROM (OLD.session_id,OLD.line_number,OLD.item_id,OLD.uom_id,OLD.inventory_lot_id,OLD.expected_quantity_scaled,OLD.quantity_precision,OLD.created_at) THEN RAISE EXCEPTION 'inventory count snapshot fields are immutable'; END IF;
 IF TG_OP='UPDATE' AND session_status<>'Counting' THEN RAISE EXCEPTION 'inventory count results can be updated only while counting'; END IF;
 IF TG_OP='DELETE' AND session_status<>'Draft' THEN RAISE EXCEPTION 'started inventory count lines are immutable'; END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS inventory_count_sessions_guard ON reconforge.inventory_count_sessions;
CREATE TRIGGER inventory_count_sessions_guard BEFORE INSERT OR UPDATE OR DELETE ON reconforge.inventory_count_sessions FOR EACH ROW EXECUTE FUNCTION reconforge.inventory_count_guard();
DROP TRIGGER IF EXISTS inventory_count_lines_guard ON reconforge.inventory_count_lines;
CREATE TRIGGER inventory_count_lines_guard BEFORE INSERT OR UPDATE OR DELETE ON reconforge.inventory_count_lines FOR EACH ROW EXECUTE FUNCTION reconforge.inventory_count_guard();

CREATE OR REPLACE FUNCTION reconforge.inventory_count_dependency_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_TABLE_NAME='inventory_movement_lines' THEN
  IF EXISTS(SELECT 1 FROM reconforge.inventory_count_sessions s WHERE s.tenant_id=COALESCE(NEW.tenant_id,OLD.tenant_id) AND s.adjustment_movement_id=COALESCE(NEW.movement_id,OLD.movement_id) AND s.status='Approved') THEN RAISE EXCEPTION 'approved inventory count adjustment lines are immutable'; END IF;
  IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;
 END IF;
 IF EXISTS(SELECT 1 FROM reconforge.inventory_count_sessions s WHERE s.tenant_id=OLD.tenant_id AND s.adjustment_movement_id=OLD.id AND s.status='Approved') THEN
  IF TG_OP='DELETE' OR (NEW.workspace_id,NEW.organization_id,NEW.legal_entity_id,NEW.period_id,NEW.movement_number,NEW.movement_type,NEW.movement_date,NEW.source_reference,NEW.description,NEW.source_type,NEW.created_by,NEW.created_at) IS DISTINCT FROM (OLD.workspace_id,OLD.organization_id,OLD.legal_entity_id,OLD.period_id,OLD.movement_number,OLD.movement_type,OLD.movement_date,OLD.source_reference,OLD.description,OLD.source_type,OLD.created_by,OLD.created_at) OR (OLD.status='Posted' AND NEW.status='Voided') THEN RAISE EXCEPTION 'approved inventory count adjustment movement evidence is immutable'; END IF;
 END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS inventory_count_adjustment_guard ON reconforge.inventory_movements;
CREATE TRIGGER inventory_count_adjustment_guard BEFORE UPDATE OR DELETE ON reconforge.inventory_movements FOR EACH ROW EXECUTE FUNCTION reconforge.inventory_count_dependency_guard();
DROP TRIGGER IF EXISTS inventory_count_adjustment_lines_guard ON reconforge.inventory_movement_lines;
CREATE TRIGGER inventory_count_adjustment_lines_guard BEFORE INSERT OR UPDATE OR DELETE ON reconforge.inventory_movement_lines FOR EACH ROW EXECUTE FUNCTION reconforge.inventory_count_dependency_guard();

DO $rls$ DECLARE table_name TEXT; BEGIN
 FOREACH table_name IN ARRAY ARRAY['inventory_count_sessions','inventory_count_lines','inventory_reorder_rules'] LOOP
  EXECUTE format('ALTER TABLE reconforge.%I ENABLE ROW LEVEL SECURITY',table_name); EXECUTE format('ALTER TABLE reconforge.%I FORCE ROW LEVEL SECURITY',table_name);
  EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON reconforge.%I',table_name);
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname='reconforge' AND tablename=table_name AND policyname='tenant_scope') THEN
   EXECUTE format('CREATE POLICY tenant_isolation ON reconforge.%I USING (tenant_id=current_setting(''app.tenant_id'',true)) WITH CHECK (tenant_id=current_setting(''app.tenant_id'',true))',table_name);
  END IF;
 END LOOP;
END $rls$;
"""


class PostgresInventoryPlanningError(RuntimeError):
    """Safe PostgreSQL inventory planning failure."""


class PostgresInventoryPlanningRepository:
    """Tenant-scoped count and advisory reorder adapter."""

    def __init__(self, connection: Any, tenant_id: str) -> None:
        self.connection = connection
        self.tenant_id = validate_tenant_id(tenant_id)

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        try:
            with self.connection.transaction():
                set_local_tenant_scope(self.connection, self.tenant_id)
                yield
        except (PlatformError, PostgresInventoryPlanningError):
            raise
        except Exception as exc:
            raise PostgresInventoryPlanningError("PostgreSQL inventory planning operation failed.") from exc

    def _one(self, sql: str, parameters: tuple[object, ...], message: str) -> dict[str, Any]:
        row = self.connection.execute(sql, parameters).fetchone()
        if row is None:
            raise PlatformError(message)
        return dict(row)

    def _event(
        self,
        *,
        actor_label: str,
        object_type: str,
        object_id: str,
        action: str,
        version: object,
        metadata: dict[str, Any],
    ) -> None:
        try:
            payload = encode_postgres_outbox_payload(metadata).text
        except PersistedJsonError as exc:
            raise PostgresInventoryPlanningError("Inventory planning event payload is invalid.") from exc
        self.connection.execute(
            "INSERT INTO reconforge.outbox_events(tenant_id,event_id,event_type,aggregate_type,aggregate_id,payload) VALUES(%s,%s,%s,%s,%s,CAST(%s AS jsonb)) ON CONFLICT(tenant_id,event_id) DO NOTHING",
            (
                self.tenant_id,
                platform_id("OBX", action, object_id, version),
                action,
                object_type,
                object_id,
                payload,
            ),
        )
        PostgresAuditEventRepository(self.connection, self.tenant_id).append(
            actor_label=clean_text(actor_label, "Actor label"),
            object_type=object_type,
            object_id=object_id,
            action=action,
            metadata=metadata,
        )

    def _workspace_id(self, workspace: str) -> str:
        row = self.connection.execute(
            "SELECT id FROM reconforge.domain_workspaces WHERE tenant_id=%s AND name=%s",
            (self.tenant_id, clean_text(workspace, "Workspace name")),
        ).fetchone()
        if row is None:
            raise PlatformError("Inventory planning workspace was not found.")
        return str(row["id"])

    def _organization(self, workspace_id: str, organization_code: object) -> dict[str, Any]:
        return self._one(
            """SELECT o.* FROM reconforge.organizations o
            JOIN reconforge.master_data_workspace_organizations w ON w.tenant_id=o.tenant_id AND w.organization_id=o.id
            WHERE o.tenant_id=%s AND w.workspace_id=%s AND o.organization_code=%s AND o.active=TRUE""",
            (self.tenant_id, workspace_id, code(organization_code, "Organization code")),
            "Inventory planning requires an active organization in this workspace.",
        )

    def _entity(self, organization_id: str, entity_code: object) -> dict[str, Any]:
        return self._one(
            "SELECT * FROM reconforge.legal_entities WHERE tenant_id=%s AND organization_id=%s AND entity_code=%s AND active=TRUE",
            (self.tenant_id, organization_id, code(entity_code, "Entity code")),
            "Inventory planning requires an active legal entity.",
        )

    def _period(self, workspace_id: str, period_id: object) -> dict[str, Any]:
        return self._one(
            """SELECT p.* FROM reconforge.fiscal_periods p JOIN reconforge.master_data_workspace_periods w
            ON w.tenant_id=p.tenant_id AND w.period_id=p.id
            WHERE p.tenant_id=%s AND w.workspace_id=%s AND p.id=%s""",
            (self.tenant_id, workspace_id, clean_text(period_id, "Period ID", maximum=160)),
            "Fiscal period was not found in this workspace.",
        )

    def _location(
        self,
        workspace_id: str,
        organization_id: str,
        entity_id: str,
        warehouse_code: object,
        location_code: object,
    ) -> dict[str, Any]:
        return self._one(
            """SELECT l.*,w.warehouse_code,w.legal_entity_id FROM reconforge.inventory_locations l
            JOIN reconforge.inventory_warehouses w ON w.tenant_id=l.tenant_id AND w.id=l.warehouse_id
            WHERE l.tenant_id=%s AND w.workspace_id=%s AND w.organization_id=%s AND w.legal_entity_id=%s
            AND w.warehouse_code=%s AND l.location_code=%s AND w.active=TRUE AND l.active=TRUE""",
            (
                self.tenant_id,
                workspace_id,
                organization_id,
                entity_id,
                code(warehouse_code, "Warehouse code"),
                code(location_code, "Location code"),
            ),
            "Active inventory location was not found in the selected entity.",
        )

    def _item(self, workspace_id: str, item_code: object) -> dict[str, Any]:
        return self._one(
            """SELECT i.*,u.uom_code,u.decimal_places FROM reconforge.inventory_items i
            JOIN reconforge.inventory_units_of_measure u ON u.tenant_id=i.tenant_id AND u.id=i.uom_id
            WHERE i.tenant_id=%s AND i.workspace_id=%s AND i.item_code=%s""",
            (self.tenant_id, workspace_id, code(item_code, "Item code")),
            "Inventory item was not found in this workspace.",
        )

    def _session(self, session_id: str, *, lock: bool = False) -> dict[str, Any]:
        query = (
            """SELECT s.*,o.organization_code,e.entity_code,p.name period_name,w.warehouse_code,
            l.location_code,l.name location_name,m.movement_number adjustment_movement_number
            FROM reconforge.inventory_count_sessions s
            JOIN reconforge.organizations o ON o.tenant_id=s.tenant_id AND o.id=s.organization_id
            JOIN reconforge.legal_entities e ON e.tenant_id=s.tenant_id AND e.id=s.legal_entity_id
            JOIN reconforge.fiscal_periods p ON p.tenant_id=s.tenant_id AND p.id=s.period_id
            JOIN reconforge.inventory_locations l ON l.tenant_id=s.tenant_id AND l.id=s.location_id
            JOIN reconforge.inventory_warehouses w ON w.tenant_id=l.tenant_id AND w.id=l.warehouse_id
            LEFT JOIN reconforge.inventory_movements m ON m.tenant_id=s.tenant_id AND m.id=s.adjustment_movement_id
            WHERE s.tenant_id=%s AND s.id=%s FOR UPDATE OF s"""
            if lock
            else """SELECT s.*,o.organization_code,e.entity_code,p.name period_name,w.warehouse_code,
            l.location_code,l.name location_name,m.movement_number adjustment_movement_number
            FROM reconforge.inventory_count_sessions s
            JOIN reconforge.organizations o ON o.tenant_id=s.tenant_id AND o.id=s.organization_id
            JOIN reconforge.legal_entities e ON e.tenant_id=s.tenant_id AND e.id=s.legal_entity_id
            JOIN reconforge.fiscal_periods p ON p.tenant_id=s.tenant_id AND p.id=s.period_id
            JOIN reconforge.inventory_locations l ON l.tenant_id=s.tenant_id AND l.id=s.location_id
            JOIN reconforge.inventory_warehouses w ON w.tenant_id=l.tenant_id AND w.id=l.warehouse_id
            LEFT JOIN reconforge.inventory_movements m ON m.tenant_id=s.tenant_id AND m.id=s.adjustment_movement_id
            WHERE s.tenant_id=%s AND s.id=%s"""
        )
        return self._one(
            query,
            (self.tenant_id, clean_text(session_id, "Inventory count session ID")),
            "Inventory count session was not found.",
        )

    def _lines(self, session_id: str) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """SELECT l.*,i.item_code,i.name item_name,u.uom_code,lot.lot_serial_code
            FROM reconforge.inventory_count_lines l
            JOIN reconforge.inventory_items i ON i.tenant_id=l.tenant_id AND i.id=l.item_id
            JOIN reconforge.inventory_units_of_measure u ON u.tenant_id=l.tenant_id AND u.id=l.uom_id
            LEFT JOIN reconforge.inventory_lots lot ON lot.tenant_id=l.tenant_id AND lot.id=l.inventory_lot_id
            WHERE l.tenant_id=%s AND l.session_id=%s ORDER BY l.line_number,l.id""",
            (self.tenant_id, session_id),
        ).fetchall()
        return [dict(row) for row in rows]

    def _balances(self, location_id: str) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """SELECT l.item_id,l.uom_id,l.inventory_lot_id,l.quantity_precision,
            SUM(CASE WHEN l.to_location_id=%s THEN l.quantity_scaled WHEN l.from_location_id=%s THEN -l.quantity_scaled ELSE 0 END) expected_quantity_scaled
            FROM reconforge.inventory_movement_lines l JOIN reconforge.inventory_movements m
            ON m.tenant_id=l.tenant_id AND m.id=l.movement_id
            WHERE l.tenant_id=%s AND m.status='Posted' AND (l.from_location_id=%s OR l.to_location_id=%s)
            GROUP BY l.item_id,l.uom_id,l.inventory_lot_id,l.quantity_precision
            HAVING SUM(CASE WHEN l.to_location_id=%s THEN l.quantity_scaled WHEN l.from_location_id=%s THEN -l.quantity_scaled ELSE 0 END)<>0
            ORDER BY l.item_id,l.inventory_lot_id""",
            (location_id, location_id, self.tenant_id, location_id, location_id, location_id, location_id),
        ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _require_open_date(period: Mapping[str, object], selected: object) -> None:
        if period["status"] != "Open":
            raise PlatformError("Inventory planning requires an Open fiscal period.")
        if str(selected) < str(period["start_date"]) or str(selected) > str(period["end_date"]):
            raise PlatformError("Count date must fall inside the selected fiscal period.")

    @staticmethod
    def _public_line(line: Mapping[str, object]) -> dict[str, Any]:
        result = public_record(line)
        precision = int(result["quantity_precision"])
        expected = int(result["expected_quantity_scaled"])
        counted_raw = result["counted_quantity_scaled"]
        counted = None if counted_raw is None else int(counted_raw)
        result["expected_quantity"] = scaled_to_text(expected, precision)
        result["counted_quantity"] = None if counted is None else scaled_to_text(counted, precision)
        result["variance_quantity_scaled"] = None if counted is None else counted - expected
        result["variance_quantity"] = None if counted is None else scaled_to_text(counted - expected, precision)
        return result

    @staticmethod
    def _public_session(session: Mapping[str, object]) -> dict[str, Any]:
        return public_record(session)

    @staticmethod
    def _public_rule(rule: Mapping[str, object]) -> dict[str, Any]:
        result = public_record(rule)
        precision = int(result["quantity_precision"])
        for field in ("minimum_quantity", "target_quantity", "on_hand_quantity"):
            scaled_field = field + "_scaled"
            if scaled_field in result:
                result[field] = scaled_to_text(int(result[scaled_field]), precision)
        return result

    def summary(self, *, workspace: str = "default", actor_label: str = "local-cli") -> InventoryPlanningSummary:
        workspace_name = clean_text(workspace, "Workspace name")
        with self._transaction():
            workspace_id = self._workspace_id(workspace_name)
            row = self.connection.execute(
                """SELECT
                (SELECT COUNT(*) FROM reconforge.inventory_count_sessions WHERE tenant_id=%s AND workspace_id=%s) sessions,
                (SELECT COUNT(*) FROM reconforge.inventory_count_sessions WHERE tenant_id=%s AND workspace_id=%s AND status='Counting') counting,
                (SELECT COUNT(*) FROM reconforge.inventory_count_sessions WHERE tenant_id=%s AND workspace_id=%s AND status='Submitted') submitted,
                (SELECT COUNT(*) FROM reconforge.inventory_count_sessions WHERE tenant_id=%s AND workspace_id=%s AND status='Approved') approved,
                (SELECT COUNT(*) FROM reconforge.inventory_reorder_rules WHERE tenant_id=%s AND workspace_id=%s) rules,
                (SELECT COUNT(*) FROM reconforge.inventory_reorder_rules WHERE tenant_id=%s AND workspace_id=%s AND active=TRUE) active""",
                (self.tenant_id, workspace_id) * 6,
            ).fetchone()
            return InventoryPlanningSummary(
                workspace_name,
                int(row["sessions"]),
                int(row["counting"]),
                int(row["submitted"]),
                int(row["approved"]),
                int(row["rules"]),
                int(row["active"]),
            )

    def create_count_session(
        self,
        *,
        count_number: str,
        organization_code: str,
        entity_code: str,
        period_id: str,
        warehouse_code: str,
        location_code: str,
        count_date: str,
        description: str = "Inventory count",
        workspace: str = "default",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        number = document_number(count_number, "Count number")
        if len(number) > 60:
            raise PlatformError("Count number must not exceed 60 characters.")
        selected_date = iso_date(count_date, "Count date")
        if selected_date is None:
            raise PlatformError("Count date is required.")
        actor = clean_text(actor_label, "Actor label")
        with self._transaction():
            workspace_id = self._workspace_id(workspace)
            organization = self._organization(workspace_id, organization_code)
            entity = self._entity(str(organization["id"]), entity_code)
            period = self._period(workspace_id, period_id)
            location = self._location(
                workspace_id, str(organization["id"]), str(entity["id"]), warehouse_code, location_code
            )
            self._require_open_date(period, selected_date)
            session_id = platform_id("ICNT", workspace_id, number)
            row = self.connection.execute(
                """INSERT INTO reconforge.inventory_count_sessions(
                tenant_id,id,workspace_id,organization_id,legal_entity_id,period_id,location_id,count_number,
                count_date,description,created_by) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING row_version""",
                (
                    self.tenant_id,
                    session_id,
                    workspace_id,
                    organization["id"],
                    entity["id"],
                    period["id"],
                    location["id"],
                    number,
                    selected_date,
                    clean_text(description, "Count description", maximum=500),
                    actor,
                ),
            ).fetchone()
            if row is None:
                raise PlatformError("Inventory count changed concurrently; reload and retry.")
            self._event(
                actor_label=actor,
                object_type="inventory_count_session",
                object_id=session_id,
                action="inventory_count_created",
                version=row["row_version"],
                metadata={"count_number": number, "location_id": location["id"]},
            )
            return self._get_session(session_id)

    def start_count_session(self, session_id: str, *, actor_label: str = "local-cli") -> dict[str, Any]:
        actor = clean_text(actor_label, "Actor label")
        with self._transaction():
            session = self._session(session_id, lock=True)
            if session["status"] != "Draft":
                raise PlatformError("Only Draft inventory count sessions can be started.")
            lock_key = f"count|{session['location_id']}"
            self.connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (lock_key,))
            balances = self._balances(str(session["location_id"]))
            if not balances:
                raise PlatformError("The selected location has no non-zero Posted balances to count.")
            if len(balances) > 100_000:
                raise PlatformError("Inventory counts cannot exceed 100000 snapshot lines.")
            for line_number, balance in enumerate(balances, start=1):
                self.connection.execute(
                    """INSERT INTO reconforge.inventory_count_lines(
                    tenant_id,id,session_id,line_number,item_id,uom_id,inventory_lot_id,
                    expected_quantity_scaled,quantity_precision) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        self.tenant_id,
                        platform_id("ICNL", session_id, line_number),
                        session_id,
                        line_number,
                        balance["item_id"],
                        balance["uom_id"],
                        balance["inventory_lot_id"],
                        balance["expected_quantity_scaled"],
                        balance["quantity_precision"],
                    ),
                )
            row = self.connection.execute(
                """UPDATE reconforge.inventory_count_sessions SET status='Counting',started_by=%s,started_at=now(),
                updated_at=now(),row_version=row_version+1 WHERE tenant_id=%s AND id=%s AND status='Draft'
                RETURNING row_version""",
                (actor, self.tenant_id, session_id),
            ).fetchone()
            if row is None:
                raise PlatformError("Inventory count changed concurrently; reload and retry.")
            self._event(
                actor_label=actor,
                object_type="inventory_count_session",
                object_id=session_id,
                action="inventory_count_started",
                version=row["row_version"],
                metadata={"snapshot_lines": len(balances)},
            )
            return self._get_session(session_id)

    def record_counted_quantity(
        self,
        session_id: str,
        line_id: str,
        *,
        counted_quantity: object,
        note: str = "",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        actor = clean_text(actor_label, "Actor label")
        with self._transaction():
            line = self._one(
                """SELECT l.*,s.status FROM reconforge.inventory_count_lines l
                JOIN reconforge.inventory_count_sessions s ON s.tenant_id=l.tenant_id AND s.id=l.session_id
                WHERE l.tenant_id=%s AND l.session_id=%s AND l.id=%s FOR UPDATE""",
                (self.tenant_id, clean_text(session_id, "Count session ID"), clean_text(line_id, "Count line ID")),
                "Inventory count line was not found.",
            )
            if line["status"] != "Counting":
                raise PlatformError("Counted quantities can be recorded only while the session is Counting.")
            scaled = quantity_to_scaled(
                counted_quantity, int(line["quantity_precision"]), "Counted quantity", allow_zero=True
            )
            row = self.connection.execute(
                """UPDATE reconforge.inventory_count_lines SET counted_quantity_scaled=%s,count_note=%s,
                counted_by=%s,counted_at=now(),row_version=row_version+1 WHERE tenant_id=%s AND id=%s
                RETURNING row_version""",
                (
                    scaled,
                    clean_text(note, "Count note", maximum=500, required=False),
                    actor,
                    self.tenant_id,
                    line_id,
                ),
            ).fetchone()
            if row is None:
                raise PlatformError("Inventory count changed concurrently; reload and retry.")
            self._event(
                actor_label=actor,
                object_type="inventory_count_line",
                object_id=line_id,
                action="inventory_count_quantity_recorded",
                version=row["row_version"],
                metadata={"session_id": session_id},
            )
            return self._get_session(session_id)

    def submit_count_session(self, session_id: str, *, reason: str, actor_label: str = "local-cli") -> dict[str, Any]:
        actor = clean_text(actor_label, "Actor label")
        submit_reason = clean_text(reason, "Submission reason", maximum=500)
        with self._transaction():
            session = self._session(session_id, lock=True)
            if session["status"] != "Counting":
                raise PlatformError("Only Counting inventory sessions can be submitted.")
            lines = self._lines(session_id)
            if not lines or any(line["counted_quantity_scaled"] is None for line in lines):
                raise PlatformError("Every inventory count line requires a counted quantity before submission.")
            row = self.connection.execute(
                """UPDATE reconforge.inventory_count_sessions SET status='Submitted',submitted_by=%s,
                submitted_at=now(),submit_reason=%s,updated_at=now(),row_version=row_version+1
                WHERE tenant_id=%s AND id=%s AND status='Counting' RETURNING row_version""",
                (actor, submit_reason, self.tenant_id, session_id),
            ).fetchone()
            if row is None:
                raise PlatformError("Inventory count changed concurrently; reload and retry.")
            self._event(
                actor_label=actor,
                object_type="inventory_count_session",
                object_id=session_id,
                action="inventory_count_submitted",
                version=row["row_version"],
                metadata={"reason": submit_reason},
            )
            return self._get_session(session_id)

    def approve_count_session(self, session_id: str, *, reason: str, actor_label: str = "local-cli") -> dict[str, Any]:
        actor = clean_text(actor_label, "Actor label")
        approval_reason = clean_text(reason, "Approval reason", maximum=500)
        with self._transaction():
            session = self._session(session_id, lock=True)
            if session["status"] != "Submitted":
                raise PlatformError("Only Submitted inventory count sessions can be approved.")
            if same_actor(session["created_by"], actor) or same_actor(session["submitted_by"], actor):
                raise PlatformError("Segregation of duties prevents approving a count you created or submitted.")
            period = self._period(str(session["workspace_id"]), session["period_id"])
            self._require_open_date(period, session["count_date"])
            lock_key = f"count|{session['location_id']}"
            self.connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (lock_key,))
            lines = self._lines(session_id)
            if not lines or any(line["counted_quantity_scaled"] is None for line in lines):
                raise PlatformError("Submitted inventory count lines are incomplete.")
            expected = {
                (str(line["item_id"]), str(line["inventory_lot_id"] or "")): int(line["expected_quantity_scaled"])
                for line in lines
            }
            current = {
                (str(line["item_id"]), str(line["inventory_lot_id"] or "")): int(line["expected_quantity_scaled"])
                for line in self._balances(str(session["location_id"]))
            }
            if current != expected:
                raise PlatformError("Posted inventory changed after this count started; start a fresh snapshot.")
            variances = [
                (line, int(line["counted_quantity_scaled"]) - int(line["expected_quantity_scaled"]))
                for line in lines
                if int(line["counted_quantity_scaled"]) != int(line["expected_quantity_scaled"])
            ]
            adjustment_id: str | None = None
            if variances:
                movement_number = f"ADJ/{session['count_number']}"
                if self.connection.execute(
                    "SELECT 1 FROM reconforge.inventory_movements WHERE tenant_id=%s AND workspace_id=%s AND movement_number=%s",
                    (self.tenant_id, session["workspace_id"], movement_number),
                ).fetchone():
                    raise PlatformError("The generated count-adjustment movement number already exists.")
                adjustment_id = platform_id("MOV", session["workspace_id"], movement_number)
                self.connection.execute(
                    """INSERT INTO reconforge.inventory_movements(
                    tenant_id,id,workspace_id,organization_id,legal_entity_id,period_id,movement_number,
                    movement_type,movement_date,source_reference,description,source_type,status,created_by)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,'Adjustment',%s,%s,%s,'Generated','Draft','inventory-count-service')""",
                    (
                        self.tenant_id,
                        adjustment_id,
                        session["workspace_id"],
                        session["organization_id"],
                        session["legal_entity_id"],
                        session["period_id"],
                        movement_number,
                        session["count_date"],
                        session_id,
                        f"Draft adjustment generated from approved count {session['count_number']}",
                    ),
                )
                for line_number, (line, variance) in enumerate(variances, start=1):
                    self.connection.execute(
                        """INSERT INTO reconforge.inventory_movement_lines(
                        tenant_id,id,movement_id,line_number,item_id,uom_id,inventory_lot_id,from_location_id,
                        to_location_id,quantity_scaled,quantity_precision,description)
                        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (
                            self.tenant_id,
                            platform_id("MOVL", adjustment_id, line_number),
                            adjustment_id,
                            line_number,
                            line["item_id"],
                            line["uom_id"],
                            line["inventory_lot_id"],
                            session["location_id"] if variance < 0 else None,
                            session["location_id"] if variance > 0 else None,
                            abs(variance),
                            line["quantity_precision"],
                            f"Count variance from {session['count_number']}",
                        ),
                    )
            row = self.connection.execute(
                """UPDATE reconforge.inventory_count_sessions SET status='Approved',approved_by=%s,
                approved_at=now(),approval_reason=%s,adjustment_movement_id=%s,updated_at=now(),
                row_version=row_version+1 WHERE tenant_id=%s AND id=%s AND status='Submitted' RETURNING row_version""",
                (actor, approval_reason, adjustment_id, self.tenant_id, session_id),
            ).fetchone()
            if row is None:
                raise PlatformError("Inventory count changed concurrently; reload and retry.")
            self._event(
                actor_label=actor,
                object_type="inventory_count_session",
                object_id=session_id,
                action="inventory_count_approved",
                version=row["row_version"],
                metadata={
                    "reason": approval_reason,
                    "variance_lines": len(variances),
                    "adjustment_movement_id": adjustment_id,
                },
            )
            if adjustment_id is not None:
                self._event(
                    actor_label=actor,
                    object_type="inventory_movement",
                    object_id=adjustment_id,
                    action="inventory_count_adjustment_draft_created",
                    version="created",
                    metadata={"count_session_id": session_id},
                )
            return self._get_session(session_id)

    def cancel_count_session(self, session_id: str, *, reason: str, actor_label: str = "local-cli") -> dict[str, Any]:
        actor = clean_text(actor_label, "Actor label")
        cancel_reason = clean_text(reason, "Cancellation reason", maximum=500)
        with self._transaction():
            session = self._session(session_id, lock=True)
            if session["status"] not in {"Draft", "Counting", "Submitted"}:
                raise PlatformError("Only Draft, Counting, or Submitted inventory counts can be cancelled.")
            row = self.connection.execute(
                """UPDATE reconforge.inventory_count_sessions SET status='Cancelled',cancelled_by=%s,
                cancelled_at=now(),cancel_reason=%s,updated_at=now(),row_version=row_version+1
                WHERE tenant_id=%s AND id=%s AND status IN('Draft','Counting','Submitted') RETURNING row_version""",
                (actor, cancel_reason, self.tenant_id, session_id),
            ).fetchone()
            if row is None:
                raise PlatformError("Inventory count changed concurrently; reload and retry.")
            self._event(
                actor_label=actor,
                object_type="inventory_count_session",
                object_id=session_id,
                action="inventory_count_cancelled",
                version=row["row_version"],
                metadata={"reason": cancel_reason},
            )
            return self._get_session(session_id)

    def _get_session(self, session_id: str) -> dict[str, Any]:
        session = self._session(session_id)
        public_lines = [self._public_line(line) for line in self._lines(session_id)]
        session["lines"] = public_lines
        session["summary"] = {
            "lines": len(public_lines),
            "counted_lines": sum(line["counted_quantity"] is not None for line in public_lines),
            "variance_lines": sum(line["variance_quantity_scaled"] not in {None, 0} for line in public_lines),
        }
        return self._public_session(session)

    def get_count_session(self, session_id: str, *, actor_label: str = "local-cli") -> dict[str, Any]:
        with self._transaction():
            return self._get_session(session_id)

    def list_count_sessions(
        self,
        *,
        workspace: str = "default",
        status: str = "",
        limit: int = 500,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]:
        selected = (
            choice(status, "Count status", ("Draft", "Counting", "Submitted", "Approved", "Cancelled"))
            if status
            else ""
        )
        limit, offset = page(limit, offset)
        with self._transaction():
            workspace_id = self._workspace_id(workspace)
            rows = self.connection.execute(
                """SELECT id FROM reconforge.inventory_count_sessions WHERE tenant_id=%s AND workspace_id=%s
                AND (%s='' OR status=%s) ORDER BY count_date DESC,count_number,id LIMIT %s OFFSET %s""",
                (self.tenant_id, workspace_id, selected, selected, limit, offset),
            ).fetchall()
            return [self._public_session(self._session(str(row["id"]))) for row in rows]

    def _rule_query(self) -> str:
        return """SELECT r.*,o.organization_code,e.entity_code,i.item_code,i.name item_name,u.uom_code,
        w.warehouse_code,l.location_code,
        COALESCE((SELECT SUM(CASE WHEN ml.to_location_id=r.location_id THEN ml.quantity_scaled
        WHEN ml.from_location_id=r.location_id THEN -ml.quantity_scaled ELSE 0 END)
        FROM reconforge.inventory_movement_lines ml JOIN reconforge.inventory_movements m
        ON m.tenant_id=ml.tenant_id AND m.id=ml.movement_id WHERE ml.tenant_id=r.tenant_id
        AND m.status='Posted' AND ml.item_id=r.item_id AND
        (ml.from_location_id=r.location_id OR ml.to_location_id=r.location_id)),0) on_hand_quantity_scaled
        FROM reconforge.inventory_reorder_rules r
        JOIN reconforge.organizations o ON o.tenant_id=r.tenant_id AND o.id=r.organization_id
        JOIN reconforge.legal_entities e ON e.tenant_id=r.tenant_id AND e.id=r.legal_entity_id
        JOIN reconforge.inventory_items i ON i.tenant_id=r.tenant_id AND i.id=r.item_id
        JOIN reconforge.inventory_units_of_measure u ON u.tenant_id=i.tenant_id AND u.id=i.uom_id
        JOIN reconforge.inventory_locations l ON l.tenant_id=r.tenant_id AND l.id=r.location_id
        JOIN reconforge.inventory_warehouses w ON w.tenant_id=l.tenant_id AND w.id=l.warehouse_id"""

    def upsert_reorder_rule(
        self,
        *,
        organization_code: str,
        entity_code: str,
        item_code: str,
        warehouse_code: str,
        location_code: str,
        minimum_quantity: object,
        target_quantity: object,
        lead_time_days: int = 0,
        active: bool = True,
        workspace: str = "default",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        if isinstance(lead_time_days, bool) or not isinstance(lead_time_days, int) or not 0 <= lead_time_days <= 3650:
            raise PlatformError("Lead time days must be an integer between 0 and 3650.")
        actor = clean_text(actor_label, "Actor label")
        with self._transaction():
            workspace_id = self._workspace_id(workspace)
            organization = self._organization(workspace_id, organization_code)
            entity = self._entity(str(organization["id"]), entity_code)
            location = self._location(
                workspace_id, str(organization["id"]), str(entity["id"]), warehouse_code, location_code
            )
            item = self._item(workspace_id, item_code)
            if item["item_type"] == "Service" or not item["active"]:
                raise PlatformError("Reorder rules require an active stock or consumable item.")
            if item["organization_id"] is not None and item["organization_id"] != organization["id"]:
                raise PlatformError("Reorder item belongs to a different organization.")
            precision = int(item["decimal_places"])
            minimum = quantity_to_scaled(minimum_quantity, precision, "Minimum quantity", allow_zero=True)
            target = quantity_to_scaled(target_quantity, precision, "Target quantity")
            if target <= minimum:
                raise PlatformError("Target quantity must be greater than minimum quantity.")
            rule_id = platform_id("IROR", workspace_id, organization["id"], entity["id"], item["id"], location["id"])
            row = self.connection.execute(
                """INSERT INTO reconforge.inventory_reorder_rules(
                tenant_id,id,workspace_id,organization_id,legal_entity_id,item_id,location_id,
                minimum_quantity_scaled,target_quantity_scaled,quantity_precision,lead_time_days,active,created_by)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(tenant_id,workspace_id,organization_id,legal_entity_id,item_id,location_id)
                DO UPDATE SET minimum_quantity_scaled=EXCLUDED.minimum_quantity_scaled,
                target_quantity_scaled=EXCLUDED.target_quantity_scaled,quantity_precision=EXCLUDED.quantity_precision,
                lead_time_days=EXCLUDED.lead_time_days,active=EXCLUDED.active,updated_at=now(),
                row_version=inventory_reorder_rules.row_version+1 RETURNING row_version""",
                (
                    self.tenant_id,
                    rule_id,
                    workspace_id,
                    organization["id"],
                    entity["id"],
                    item["id"],
                    location["id"],
                    minimum,
                    target,
                    precision,
                    lead_time_days,
                    bool(active),
                    actor,
                ),
            ).fetchone()
            self._event(
                actor_label=actor,
                object_type="inventory_reorder_rule",
                object_id=rule_id,
                action="inventory_reorder_rule_upserted",
                version=row["row_version"],
                metadata={"item_code": item["item_code"], "location_id": location["id"]},
            )
            saved = self.connection.execute(
                self._rule_query() + " WHERE r.tenant_id=%s AND r.id=%s",
                (self.tenant_id, rule_id),
            ).fetchone()
            return self._public_rule(dict(saved))

    def list_reorder_rules(
        self,
        *,
        workspace: str = "default",
        active_only: bool = False,
        limit: int = 500,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]:
        limit, offset = page(limit, offset)
        with self._transaction():
            workspace_id = self._workspace_id(workspace)
            rows = self.connection.execute(
                self._rule_query()
                + " WHERE r.tenant_id=%s AND r.workspace_id=%s AND (%s=FALSE OR r.active=TRUE) ORDER BY i.item_code,w.warehouse_code,l.location_code,r.id LIMIT %s OFFSET %s",
                (self.tenant_id, workspace_id, active_only, limit, offset),
            ).fetchall()
            return [self._public_rule(dict(row)) for row in rows]

    def reorder_signals(
        self,
        *,
        organization_code: str,
        entity_code: str,
        workspace: str = "default",
        limit: int = 500,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> dict[str, object]:
        limit, offset = page(limit, offset)
        workspace_name = clean_text(workspace, "Workspace name")
        with self._transaction():
            workspace_id = self._workspace_id(workspace_name)
            organization = self._organization(workspace_id, organization_code)
            entity = self._entity(str(organization["id"]), entity_code)
            rows = self.connection.execute(
                self._rule_query()
                + " WHERE r.tenant_id=%s AND r.workspace_id=%s AND r.organization_id=%s AND r.legal_entity_id=%s AND r.active=TRUE ORDER BY i.item_code,w.warehouse_code,l.location_code,r.id LIMIT %s",
                (self.tenant_id, workspace_id, organization["id"], entity["id"], MAX_LIST_LIMIT),
            ).fetchall()
            signals: list[dict[str, object]] = []
            for raw in rows:
                row = dict(raw)
                on_hand = int(row["on_hand_quantity_scaled"])
                minimum = int(row["minimum_quantity_scaled"])
                if on_hand > minimum:
                    continue
                target = int(row["target_quantity_scaled"])
                precision = int(row["quantity_precision"])
                signals.append(
                    {
                        "signal_id": platform_id("IRS", row["id"], on_hand),
                        "rule_id": row["id"],
                        "risk_rating": "high" if on_hand < 0 else "medium",
                        "item_code": row["item_code"],
                        "item_name": row["item_name"],
                        "warehouse_code": row["warehouse_code"],
                        "location_code": row["location_code"],
                        "uom_code": row["uom_code"],
                        "quantity_precision": precision,
                        "on_hand_quantity_scaled": on_hand,
                        "on_hand_quantity": scaled_to_text(on_hand, precision),
                        "minimum_quantity_scaled": minimum,
                        "minimum_quantity": scaled_to_text(minimum, precision),
                        "target_quantity_scaled": target,
                        "target_quantity": scaled_to_text(target, precision),
                        "suggested_quantity_scaled": target - on_hand,
                        "suggested_quantity": scaled_to_text(target - on_hand, precision),
                        "lead_time_days": int(row["lead_time_days"]),
                        "description": "Local on-hand is at or below the configured reorder minimum.",
                    }
                )
            signals.sort(
                key=lambda signal: (
                    0 if signal["risk_rating"] == "high" else 1,
                    str(signal["item_code"]),
                    str(signal["signal_id"]),
                )
            )
            total = len(signals)
            selected = signals[offset : offset + limit]
            return {
                "schema_version": 1,
                "generated_at": utc_now_text(),
                "source": {
                    "kind": "local-inventory-reorder-controls",
                    "local_first": True,
                    "external_calls": False,
                },
                "workspace": workspace_name,
                "organization_code": organization["organization_code"],
                "entity_code": entity["entity_code"],
                "summary": {
                    "total": total,
                    "high": sum(signal["risk_rating"] == "high" for signal in signals),
                    "medium": sum(signal["risk_rating"] == "medium" for signal in signals),
                },
                "pagination": {"limit": limit, "offset": offset, "returned": len(selected)},
                "signals": selected,
            }

    def snapshot(self, *, workspace: str = "default", actor_label: str = "local-cli") -> dict[str, object]:
        workspace_name = clean_text(workspace, "Workspace name")
        return {
            "schema_version": 1,
            "generated_at": utc_now_text(),
            "source": {"kind": "local-inventory-planning", "local_first": True, "external_calls": False},
            "workspace": workspace_name,
            "summary": self.summary(workspace=workspace_name, actor_label=actor_label).to_dict(),
            "count_sessions": self.list_count_sessions(
                workspace=workspace_name, limit=MAX_LIST_LIMIT, actor_label=actor_label
            ),
            "reorder_rules": self.list_reorder_rules(
                workspace=workspace_name, limit=MAX_LIST_LIMIT, actor_label=actor_label
            ),
        }
