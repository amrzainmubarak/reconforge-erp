"""PostgreSQL aggregate for immutable FIFO inventory valuation reversals."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from hashlib import sha256
from typing import Any

from reconforge.application.inventory_valuation_reversal import InventoryValuationReversalSummary
from reconforge.auth.rbac import same_actor
from reconforge.infrastructure.postgres import set_local_tenant_scope, validate_tenant_id
from reconforge.infrastructure.postgres_domain import PostgresAuditEventRepository
from reconforge.io.persisted import PersistedJsonError, encode_postgres_outbox_payload
from reconforge.platform.common import PlatformError, platform_id
from reconforge.platform.inventory_values import (
    MAX_AMOUNT_MINOR,
    clean_text,
    document_number,
    minor_to_text,
    page,
    public_record,
    scaled_to_text,
)
from reconforge.utils.time import utc_now_text

POSTGRES_INVENTORY_VALUATION_REVERSAL_SCHEMA_SQL = r"""
CREATE TABLE IF NOT EXISTS reconforge.inventory_valuation_reversals (
 tenant_id TEXT NOT NULL,id TEXT NOT NULL,workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,
 legal_entity_id TEXT NOT NULL,period_id TEXT NOT NULL,original_valuation_document_id TEXT NOT NULL,
 reversal_movement_id TEXT NOT NULL,reversal_number TEXT NOT NULL,reversal_date DATE NOT NULL,
 currency_code TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'Draft' CHECK(status IN('Draft','Approved','Cancelled')),
 total_value_minor BIGINT NOT NULL DEFAULT 0 CHECK(total_value_minor>=0),finance_entry_id TEXT,
 created_by TEXT NOT NULL,approved_by TEXT NOT NULL DEFAULT '',approved_at TIMESTAMPTZ,
 approval_reason TEXT NOT NULL DEFAULT '',cancelled_by TEXT NOT NULL DEFAULT '',cancelled_at TIMESTAMPTZ,
 cancel_reason TEXT NOT NULL DEFAULT '',created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),row_version BIGINT NOT NULL DEFAULT 1 CHECK(row_version>0),
 PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,workspace_id,reversal_number),UNIQUE(tenant_id,finance_entry_id),
 FOREIGN KEY(tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id) ON DELETE CASCADE,
 FOREIGN KEY(tenant_id,organization_id) REFERENCES reconforge.organizations(tenant_id,id) ON DELETE RESTRICT,
 FOREIGN KEY(tenant_id,legal_entity_id) REFERENCES reconforge.legal_entities(tenant_id,id) ON DELETE RESTRICT,
 FOREIGN KEY(tenant_id,period_id) REFERENCES reconforge.fiscal_periods(tenant_id,id) ON DELETE RESTRICT,
 FOREIGN KEY(tenant_id,original_valuation_document_id) REFERENCES reconforge.inventory_valuation_documents(tenant_id,id) ON DELETE RESTRICT,
 FOREIGN KEY(tenant_id,reversal_movement_id) REFERENCES reconforge.inventory_movements(tenant_id,id) ON DELETE RESTRICT,
 FOREIGN KEY(tenant_id,currency_code) REFERENCES reconforge.currencies(tenant_id,code) ON DELETE RESTRICT,
 FOREIGN KEY(tenant_id,finance_entry_id) REFERENCES reconforge.finance_entries(tenant_id,id) ON DELETE RESTRICT,
 CHECK(status='Draft' OR (status='Approved' AND total_value_minor>0 AND finance_entry_id IS NOT NULL) OR status='Cancelled')
);
CREATE TABLE IF NOT EXISTS reconforge.inventory_valuation_reversal_effects (
 tenant_id TEXT NOT NULL,id TEXT NOT NULL,reversal_id TEXT NOT NULL,original_valuation_line_id TEXT NOT NULL,
 original_consumption_id TEXT,cost_layer_id TEXT NOT NULL,effect_type TEXT NOT NULL CHECK(effect_type IN('Restore','Remove')),
 quantity_scaled BIGINT NOT NULL CHECK(quantity_scaled>0),value_minor BIGINT NOT NULL CHECK(value_minor>0),
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),PRIMARY KEY(tenant_id,id),
 FOREIGN KEY(tenant_id,reversal_id) REFERENCES reconforge.inventory_valuation_reversals(tenant_id,id) ON DELETE CASCADE,
 FOREIGN KEY(tenant_id,original_valuation_line_id) REFERENCES reconforge.inventory_valuation_lines(tenant_id,id) ON DELETE RESTRICT,
 FOREIGN KEY(tenant_id,original_consumption_id) REFERENCES reconforge.inventory_layer_consumptions(tenant_id,id) ON DELETE RESTRICT,
 FOREIGN KEY(tenant_id,cost_layer_id) REFERENCES reconforge.inventory_cost_layers(tenant_id,id) ON DELETE RESTRICT,
 CHECK((effect_type='Remove' AND original_consumption_id IS NULL) OR (effect_type='Restore' AND original_consumption_id IS NOT NULL))
);
CREATE UNIQUE INDEX IF NOT EXISTS inventory_valuation_reversal_active_document_idx
 ON reconforge.inventory_valuation_reversals(tenant_id,original_valuation_document_id) WHERE status<>'Cancelled';
CREATE UNIQUE INDEX IF NOT EXISTS inventory_valuation_reversal_active_movement_idx
 ON reconforge.inventory_valuation_reversals(tenant_id,reversal_movement_id) WHERE status<>'Cancelled';
CREATE INDEX IF NOT EXISTS inventory_valuation_reversals_scope_idx
 ON reconforge.inventory_valuation_reversals(tenant_id,workspace_id,status,reversal_date,id);
CREATE UNIQUE INDEX IF NOT EXISTS inventory_valuation_reversal_remove_line_idx
 ON reconforge.inventory_valuation_reversal_effects(tenant_id,reversal_id,original_valuation_line_id) WHERE effect_type='Remove';
CREATE UNIQUE INDEX IF NOT EXISTS inventory_valuation_reversal_restore_consumption_idx
 ON reconforge.inventory_valuation_reversal_effects(tenant_id,reversal_id,original_consumption_id) WHERE effect_type='Restore';

CREATE OR REPLACE FUNCTION reconforge.inventory_valuation_reversal_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_TABLE_NAME='inventory_valuation_reversals' THEN
  IF TG_OP='INSERT' AND (NEW.status<>'Draft' OR NEW.total_value_minor<>0 OR NEW.finance_entry_id IS NOT NULL) THEN RAISE EXCEPTION 'inventory valuation reversals must be created as empty Draft records'; END IF;
  IF TG_OP='UPDATE' AND NEW.status<>OLD.status AND NOT (OLD.status='Draft' AND NEW.status IN('Approved','Cancelled')) THEN RAISE EXCEPTION 'invalid inventory valuation reversal status transition'; END IF;
  IF TG_OP='UPDATE' AND OLD.status='Draft' AND NEW.status='Cancelled' AND (NEW.cancelled_by='' OR NEW.cancelled_at IS NULL OR NEW.cancel_reason='') THEN RAISE EXCEPTION 'cancelling a valuation reversal requires actor timestamp and reason'; END IF;
  IF TG_OP='UPDATE' AND OLD.status='Draft' AND NEW.status='Approved' AND (
    NEW.approved_by='' OR NEW.approved_at IS NULL OR NEW.approval_reason='' OR NEW.total_value_minor<=0 OR NEW.finance_entry_id IS NULL OR
    NOT EXISTS(SELECT 1 FROM reconforge.inventory_valuation_documents d WHERE d.tenant_id=OLD.tenant_id AND d.id=OLD.original_valuation_document_id AND d.status='Approved' AND d.workspace_id=OLD.workspace_id AND d.organization_id=OLD.organization_id AND d.legal_entity_id=OLD.legal_entity_id AND d.currency_code=OLD.currency_code AND d.total_value_minor=NEW.total_value_minor) OR
    NOT EXISTS(SELECT 1 FROM reconforge.inventory_movements m WHERE m.tenant_id=OLD.tenant_id AND m.id=OLD.reversal_movement_id AND m.status='Posted' AND m.workspace_id=OLD.workspace_id AND m.organization_id=OLD.organization_id AND m.legal_entity_id=OLD.legal_entity_id AND m.period_id=OLD.period_id AND m.movement_date=OLD.reversal_date) OR
    NOT EXISTS(SELECT 1 FROM reconforge.inventory_valuation_documents d JOIN reconforge.inventory_movements om ON om.tenant_id=d.tenant_id AND om.id=d.movement_id JOIN reconforge.inventory_movements rm ON rm.tenant_id=d.tenant_id AND rm.id=OLD.reversal_movement_id WHERE d.tenant_id=OLD.tenant_id AND d.id=OLD.original_valuation_document_id AND ((om.movement_type='Receipt' AND rm.movement_type='Delivery') OR (om.movement_type='Delivery' AND rm.movement_type='Receipt') OR (om.movement_type='Adjustment' AND rm.movement_type='Adjustment'))) OR
    EXISTS(SELECT 1 FROM reconforge.inventory_valuation_documents d JOIN reconforge.inventory_movement_lines ol ON ol.tenant_id=d.tenant_id AND ol.movement_id=d.movement_id LEFT JOIN reconforge.inventory_movement_lines rl ON rl.tenant_id=d.tenant_id AND rl.movement_id=OLD.reversal_movement_id AND rl.line_number=ol.line_number AND rl.item_id=ol.item_id AND rl.uom_id=ol.uom_id AND rl.inventory_lot_id IS NOT DISTINCT FROM ol.inventory_lot_id AND rl.from_location_id IS NOT DISTINCT FROM ol.to_location_id AND rl.to_location_id IS NOT DISTINCT FROM ol.from_location_id AND rl.quantity_scaled=ol.quantity_scaled AND rl.quantity_precision=ol.quantity_precision WHERE d.tenant_id=OLD.tenant_id AND d.id=OLD.original_valuation_document_id AND rl.id IS NULL) OR
    (SELECT COUNT(*) FROM reconforge.inventory_movement_lines WHERE tenant_id=OLD.tenant_id AND movement_id=OLD.reversal_movement_id)<>(SELECT COUNT(*) FROM reconforge.inventory_valuation_documents d JOIN reconforge.inventory_movement_lines l ON l.tenant_id=d.tenant_id AND l.movement_id=d.movement_id WHERE d.tenant_id=OLD.tenant_id AND d.id=OLD.original_valuation_document_id) OR
    NEW.total_value_minor<>(SELECT COALESCE(SUM(value_minor),0) FROM reconforge.inventory_valuation_reversal_effects WHERE tenant_id=OLD.tenant_id AND reversal_id=OLD.id) OR
    NOT EXISTS(SELECT 1 FROM reconforge.finance_entries e WHERE e.tenant_id=OLD.tenant_id AND e.id=NEW.finance_entry_id AND e.status='Draft' AND e.workspace_id=OLD.workspace_id AND e.organization_code=(SELECT organization_code FROM reconforge.organizations WHERE tenant_id=OLD.tenant_id AND id=OLD.organization_id) AND e.period_id=OLD.period_id AND e.posting_date=OLD.reversal_date::text AND e.currency_code=OLD.currency_code AND e.total_debit_minor=NEW.total_value_minor AND e.total_credit_minor=NEW.total_value_minor) OR
    (SELECT COUNT(*) FROM reconforge.finance_entry_lines WHERE tenant_id=OLD.tenant_id AND entry_id=NEW.finance_entry_id)<>(SELECT COUNT(*) FROM reconforge.inventory_valuation_documents d JOIN reconforge.finance_entry_lines l ON l.tenant_id=d.tenant_id AND l.entry_id=d.finance_entry_id WHERE d.tenant_id=OLD.tenant_id AND d.id=OLD.original_valuation_document_id) OR
    EXISTS(SELECT 1 FROM reconforge.inventory_valuation_documents d JOIN reconforge.finance_entry_lines ol ON ol.tenant_id=d.tenant_id AND ol.entry_id=d.finance_entry_id WHERE d.tenant_id=OLD.tenant_id AND d.id=OLD.original_valuation_document_id AND NOT EXISTS(SELECT 1 FROM reconforge.finance_entry_lines rl WHERE rl.tenant_id=ol.tenant_id AND rl.entry_id=NEW.finance_entry_id AND rl.line_number=ol.line_number AND rl.account_id=ol.account_id AND rl.debit_minor=ol.credit_minor AND rl.credit_minor=ol.debit_minor AND rl.currency_code=ol.currency_code)) OR
    EXISTS(SELECT 1 FROM reconforge.inventory_valuation_lines l WHERE l.tenant_id=OLD.tenant_id AND l.valuation_document_id=OLD.original_valuation_document_id AND l.flow_direction='Inbound' AND NOT EXISTS(SELECT 1 FROM reconforge.inventory_valuation_reversal_effects x WHERE x.tenant_id=l.tenant_id AND x.reversal_id=OLD.id AND x.original_valuation_line_id=l.id AND x.effect_type='Remove' AND x.quantity_scaled=l.quantity_scaled AND x.value_minor=l.value_minor)) OR
    EXISTS(SELECT 1 FROM reconforge.inventory_layer_consumptions c JOIN reconforge.inventory_valuation_lines l ON l.tenant_id=c.tenant_id AND l.id=c.valuation_line_id WHERE l.tenant_id=OLD.tenant_id AND l.valuation_document_id=OLD.original_valuation_document_id AND NOT EXISTS(SELECT 1 FROM reconforge.inventory_valuation_reversal_effects x WHERE x.tenant_id=c.tenant_id AND x.reversal_id=OLD.id AND x.original_consumption_id=c.id AND x.effect_type='Restore' AND x.cost_layer_id=c.cost_layer_id AND x.quantity_scaled=c.quantity_scaled AND x.value_minor=c.value_minor))
   ) THEN RAISE EXCEPTION 'valuation reversal approval requires exact mirror movement layer effects and finance draft'; END IF;
  IF TG_OP='UPDATE' AND OLD.status<>'Draft' AND (NEW.workspace_id,NEW.organization_id,NEW.legal_entity_id,NEW.period_id,NEW.original_valuation_document_id,NEW.reversal_movement_id,NEW.reversal_number,NEW.reversal_date,NEW.currency_code,NEW.created_by,NEW.created_at,NEW.approved_by,NEW.approved_at,NEW.approval_reason,NEW.total_value_minor,NEW.finance_entry_id,NEW.cancelled_by,NEW.cancelled_at,NEW.cancel_reason) IS DISTINCT FROM (OLD.workspace_id,OLD.organization_id,OLD.legal_entity_id,OLD.period_id,OLD.original_valuation_document_id,OLD.reversal_movement_id,OLD.reversal_number,OLD.reversal_date,OLD.currency_code,OLD.created_by,OLD.created_at,OLD.approved_by,OLD.approved_at,OLD.approval_reason,OLD.total_value_minor,OLD.finance_entry_id,OLD.cancelled_by,OLD.cancelled_at,OLD.cancel_reason) THEN RAISE EXCEPTION 'final valuation reversal headers and lifecycle metadata are immutable'; END IF;
  IF TG_OP='DELETE' AND OLD.status<>'Draft' THEN RAISE EXCEPTION 'approved valuation reversals cannot be deleted'; END IF;
  IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;
 END IF;
 IF TG_OP='INSERT' AND EXISTS(SELECT 1 FROM reconforge.inventory_valuation_reversals r WHERE r.tenant_id=NEW.tenant_id AND r.id=NEW.reversal_id AND r.status='Draft') THEN RETURN NEW; END IF;
 IF TG_OP='DELETE' AND EXISTS(SELECT 1 FROM reconforge.inventory_valuation_reversals r WHERE r.tenant_id=OLD.tenant_id AND r.id=OLD.reversal_id AND r.status='Draft') THEN RETURN OLD; END IF;
 RAISE EXCEPTION 'valuation reversal layer effects are immutable and require a Draft reversal';
END $$;
DROP TRIGGER IF EXISTS inventory_valuation_reversals_guard ON reconforge.inventory_valuation_reversals;
CREATE TRIGGER inventory_valuation_reversals_guard BEFORE INSERT OR UPDATE OR DELETE ON reconforge.inventory_valuation_reversals FOR EACH ROW EXECUTE FUNCTION reconforge.inventory_valuation_reversal_guard();
DROP TRIGGER IF EXISTS inventory_valuation_reversal_effects_guard ON reconforge.inventory_valuation_reversal_effects;
CREATE TRIGGER inventory_valuation_reversal_effects_guard BEFORE INSERT OR UPDATE OR DELETE ON reconforge.inventory_valuation_reversal_effects FOR EACH ROW EXECUTE FUNCTION reconforge.inventory_valuation_reversal_guard();

CREATE OR REPLACE FUNCTION reconforge.inventory_cost_layer_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'inventory cost layers cannot be deleted'; END IF;
 IF TG_OP='INSERT' THEN
  IF NOT EXISTS(SELECT 1 FROM reconforge.inventory_valuation_lines v JOIN reconforge.inventory_valuation_documents d ON d.tenant_id=v.tenant_id AND d.id=v.valuation_document_id WHERE v.tenant_id=NEW.tenant_id AND v.id=NEW.source_valuation_line_id AND v.flow_direction='Inbound' AND d.status='Draft') THEN RAISE EXCEPTION 'inventory cost layers require an inbound Draft valuation line'; END IF;
  RETURN NEW;
 END IF;
 IF (NEW.source_valuation_line_id,NEW.legal_entity_id,NEW.item_id,NEW.uom_id,NEW.inventory_lot_id,NEW.quantity_precision,NEW.original_quantity_scaled,NEW.original_value_minor,NEW.currency_code,NEW.created_at) IS DISTINCT FROM (OLD.source_valuation_line_id,OLD.legal_entity_id,OLD.item_id,OLD.uom_id,OLD.inventory_lot_id,OLD.quantity_precision,OLD.original_quantity_scaled,OLD.original_value_minor,OLD.currency_code,OLD.created_at) THEN RAISE EXCEPTION 'inventory cost layer identity is immutable'; END IF;
 IF NEW.remaining_quantity_scaled<>OLD.original_quantity_scaled-(SELECT COALESCE(SUM(quantity_scaled),0) FROM reconforge.inventory_layer_consumptions WHERE tenant_id=OLD.tenant_id AND cost_layer_id=OLD.id)+(SELECT COALESCE(SUM(CASE effect_type WHEN 'Restore' THEN quantity_scaled ELSE -quantity_scaled END),0) FROM reconforge.inventory_valuation_reversal_effects WHERE tenant_id=OLD.tenant_id AND cost_layer_id=OLD.id) OR NEW.remaining_value_minor<>OLD.original_value_minor-(SELECT COALESCE(SUM(value_minor),0) FROM reconforge.inventory_layer_consumptions WHERE tenant_id=OLD.tenant_id AND cost_layer_id=OLD.id)+(SELECT COALESCE(SUM(CASE effect_type WHEN 'Restore' THEN value_minor ELSE -value_minor END),0) FROM reconforge.inventory_valuation_reversal_effects WHERE tenant_id=OLD.tenant_id AND cost_layer_id=OLD.id) THEN RAISE EXCEPTION 'cost layer balances must equal immutable consumption and reversal records'; END IF;
 RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION reconforge.inventory_reversal_dependency_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_TABLE_NAME='inventory_movements' THEN
  IF OLD.status='Posted' AND NEW.status='Voided' AND EXISTS(SELECT 1 FROM reconforge.inventory_valuation_reversals r WHERE r.tenant_id=OLD.tenant_id AND r.reversal_movement_id=OLD.id AND r.status='Approved') THEN RAISE EXCEPTION 'approved valuation reversal movement cannot be voided'; END IF;
  RETURN NEW;
 END IF;
 IF TG_TABLE_NAME='finance_entries' THEN
  IF EXISTS(SELECT 1 FROM reconforge.inventory_valuation_reversals r WHERE r.tenant_id=OLD.tenant_id AND r.finance_entry_id=OLD.id AND r.status='Approved') THEN
   IF TG_OP='DELETE' THEN RAISE EXCEPTION 'approved valuation reversal finance evidence is immutable'; END IF;
   IF (NEW.workspace_id,NEW.journal_id,NEW.organization_code,NEW.entity_code,NEW.period_id,NEW.entry_number,NEW.posting_date,NEW.description,NEW.external_reference,NEW.source_type,NEW.currency_code,NEW.total_debit_minor,NEW.total_credit_minor,NEW.created_by,NEW.created_at) IS DISTINCT FROM (OLD.workspace_id,OLD.journal_id,OLD.organization_code,OLD.entity_code,OLD.period_id,OLD.entry_number,OLD.posting_date,OLD.description,OLD.external_reference,OLD.source_type,OLD.currency_code,OLD.total_debit_minor,OLD.total_credit_minor,OLD.created_by,OLD.created_at) OR (OLD.status='Validated' AND NEW.status='Voided') THEN RAISE EXCEPTION 'approved valuation reversal finance evidence is immutable'; END IF;
  END IF;
  IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;
 END IF;
 IF TG_TABLE_NAME='finance_entry_lines' THEN
  IF EXISTS(SELECT 1 FROM reconforge.inventory_valuation_reversals r WHERE r.tenant_id=COALESCE(NEW.tenant_id,OLD.tenant_id) AND r.finance_entry_id=COALESCE(NEW.entry_id,OLD.entry_id) AND r.status='Approved') THEN RAISE EXCEPTION 'approved valuation reversal finance evidence is immutable'; END IF;
  IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;
 END IF;
 IF EXISTS(SELECT 1 FROM reconforge.finance_entry_lines l JOIN reconforge.inventory_valuation_reversals r ON r.tenant_id=l.tenant_id AND r.finance_entry_id=l.entry_id WHERE l.tenant_id=COALESCE(NEW.tenant_id,OLD.tenant_id) AND l.id=COALESCE(NEW.entry_line_id,OLD.entry_line_id) AND r.status='Approved') THEN RAISE EXCEPTION 'approved valuation reversal finance evidence is immutable'; END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS inventory_reversal_finance_entries_guard ON reconforge.finance_entries;
CREATE TRIGGER inventory_reversal_finance_entries_guard BEFORE UPDATE OR DELETE ON reconforge.finance_entries FOR EACH ROW EXECUTE FUNCTION reconforge.inventory_reversal_dependency_guard();
DROP TRIGGER IF EXISTS inventory_reversal_finance_lines_guard ON reconforge.finance_entry_lines;
CREATE TRIGGER inventory_reversal_finance_lines_guard BEFORE INSERT OR UPDATE OR DELETE ON reconforge.finance_entry_lines FOR EACH ROW EXECUTE FUNCTION reconforge.inventory_reversal_dependency_guard();
DROP TRIGGER IF EXISTS inventory_reversal_finance_dimensions_guard ON reconforge.finance_entry_line_dimensions;
CREATE TRIGGER inventory_reversal_finance_dimensions_guard BEFORE INSERT OR UPDATE OR DELETE ON reconforge.finance_entry_line_dimensions FOR EACH ROW EXECUTE FUNCTION reconforge.inventory_reversal_dependency_guard();
DROP TRIGGER IF EXISTS inventory_reversal_movements_guard ON reconforge.inventory_movements;
CREATE TRIGGER inventory_reversal_movements_guard BEFORE UPDATE ON reconforge.inventory_movements FOR EACH ROW EXECUTE FUNCTION reconforge.inventory_reversal_dependency_guard();

DO $rls$ DECLARE table_name TEXT; BEGIN
 FOREACH table_name IN ARRAY ARRAY['inventory_valuation_reversals','inventory_valuation_reversal_effects'] LOOP
  EXECUTE format('ALTER TABLE reconforge.%I ENABLE ROW LEVEL SECURITY',table_name); EXECUTE format('ALTER TABLE reconforge.%I FORCE ROW LEVEL SECURITY',table_name);
  EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON reconforge.%I',table_name);
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname='reconforge' AND tablename=table_name AND policyname='tenant_scope') THEN
   EXECUTE format('CREATE POLICY tenant_isolation ON reconforge.%I USING (tenant_id=current_setting(''app.tenant_id'',true)) WITH CHECK (tenant_id=current_setting(''app.tenant_id'',true))',table_name);
  END IF;
 END LOOP;
END $rls$;
"""


class PostgresInventoryValuationReversalError(RuntimeError):
    """Safe PostgreSQL valuation-reversal failure."""


class PostgresInventoryValuationReversalRepository:
    """Tenant-scoped compensating FIFO valuation workflow."""

    def __init__(self, connection: Any, tenant_id: str) -> None:
        self.connection = connection
        self.tenant_id = validate_tenant_id(tenant_id)

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        try:
            with self.connection.transaction():
                set_local_tenant_scope(self.connection, self.tenant_id)
                yield
        except (PlatformError, PostgresInventoryValuationReversalError):
            raise
        except Exception as exc:
            raise PostgresInventoryValuationReversalError(
                "PostgreSQL inventory valuation reversal operation failed."
            ) from exc

    def _one(self, sql: str, parameters: tuple[object, ...], message: str) -> dict[str, Any]:
        row = self.connection.execute(sql, parameters).fetchone()
        if row is None:
            raise PlatformError(message)
        return dict(row)

    def _workspace_id(self, workspace: str) -> str:
        row = self.connection.execute(
            "SELECT id FROM reconforge.domain_workspaces WHERE tenant_id=%s AND name=%s",
            (self.tenant_id, clean_text(workspace, "Workspace name")),
        ).fetchone()
        if row is None:
            raise PlatformError("Inventory valuation reversal workspace was not found.")
        return str(row["id"])

    def _event(
        self,
        *,
        actor_label: str,
        object_id: str,
        action: str,
        version: object,
        metadata: dict[str, Any],
    ) -> None:
        try:
            payload = encode_postgres_outbox_payload(metadata).text
        except PersistedJsonError as exc:
            raise PostgresInventoryValuationReversalError("Valuation reversal event payload is invalid.") from exc
        self.connection.execute(
            "INSERT INTO reconforge.outbox_events(tenant_id,event_id,event_type,aggregate_type,aggregate_id,payload) VALUES(%s,%s,%s,'inventory_valuation_reversal',%s,CAST(%s AS jsonb)) ON CONFLICT(tenant_id,event_id) DO NOTHING",
            (self.tenant_id, platform_id("OBX", action, object_id, version), action, object_id, payload),
        )
        PostgresAuditEventRepository(self.connection, self.tenant_id).append(
            actor_label=clean_text(actor_label, "Actor label"),
            object_type="inventory_valuation_reversal",
            object_id=object_id,
            action=action,
            metadata=metadata,
        )

    def _original(self, document_id: str) -> dict[str, Any]:
        return self._one(
            """SELECT d.*,m.movement_number original_movement_number,m.movement_type original_movement_type,
            m.movement_date original_movement_date,e.journal_id,e.organization_code,e.entity_code
            FROM reconforge.inventory_valuation_documents d
            JOIN reconforge.inventory_movements m ON m.tenant_id=d.tenant_id AND m.id=d.movement_id
            LEFT JOIN reconforge.finance_entries e ON e.tenant_id=d.tenant_id AND e.id=d.finance_entry_id
            WHERE d.tenant_id=%s AND d.id=%s""",
            (self.tenant_id, clean_text(document_id, "Original valuation document ID")),
            "Original inventory valuation was not found.",
        )

    def _movement(self, movement_id: str) -> dict[str, Any]:
        return self._one(
            """SELECT m.*,o.organization_code,e.entity_code,e.currency_code entity_currency,
            p.status period_status,p.start_date period_start_date,p.end_date period_end_date,p.name period_name
            FROM reconforge.inventory_movements m
            JOIN reconforge.organizations o ON o.tenant_id=m.tenant_id AND o.id=m.organization_id
            JOIN reconforge.legal_entities e ON e.tenant_id=m.tenant_id AND e.id=m.legal_entity_id
            JOIN reconforge.fiscal_periods p ON p.tenant_id=m.tenant_id AND p.id=m.period_id
            WHERE m.tenant_id=%s AND m.id=%s""",
            (self.tenant_id, clean_text(movement_id, "Reversal movement ID")),
            "Reversal inventory movement was not found.",
        )

    def _movement_lines(self, movement_id: str) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT * FROM reconforge.inventory_movement_lines WHERE tenant_id=%s AND movement_id=%s ORDER BY line_number,id",
            (self.tenant_id, movement_id),
        ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _expected_type(original_type: str) -> str:
        mapping = {"Receipt": "Delivery", "Delivery": "Receipt", "Adjustment": "Adjustment"}
        try:
            return mapping[original_type]
        except KeyError as exc:
            raise PlatformError("Transfers and unsupported movements cannot be valuation-reversed.") from exc

    def _validate_scope_and_mirror(self, original: Mapping[str, object], movement: Mapping[str, object]) -> None:
        if movement["id"] == original["movement_id"]:
            raise PlatformError("The original movement cannot serve as its own compensating movement.")
        if movement["status"] != "Posted" or movement["period_status"] != "Open":
            raise PlatformError("Valuation reversal requires a separately Posted movement in an Open period.")
        if str(movement["movement_date"]) < str(original["original_movement_date"]):
            raise PlatformError("Compensating movement cannot predate the original valued movement.")
        for field, label in (
            ("workspace_id", "workspace"),
            ("organization_id", "organization"),
            ("legal_entity_id", "legal entity"),
        ):
            if movement[field] != original[field]:
                raise PlatformError(f"Compensating movement must use the original valuation {label}.")
        if movement["entity_currency"] != original["currency_code"]:
            raise PlatformError("Compensating movement currency must match the original valuation.")
        expected_type = self._expected_type(str(original["original_movement_type"]))
        if movement["movement_type"] != expected_type:
            raise PlatformError(f"Compensating movement type must be {expected_type}.")
        original_lines = self._movement_lines(str(original["movement_id"]))
        reversal_lines = self._movement_lines(str(movement["id"]))
        if not original_lines or len(original_lines) != len(reversal_lines):
            raise PlatformError("Compensating movement must mirror every original line exactly.")
        reversal_by_number = {int(line["line_number"]): line for line in reversal_lines}
        for line in original_lines:
            mirror = reversal_by_number.get(int(line["line_number"]))
            if mirror is None or any(
                mirror.get(field) != expected
                for field, expected in (
                    ("item_id", line["item_id"]),
                    ("uom_id", line["uom_id"]),
                    ("inventory_lot_id", line.get("inventory_lot_id")),
                    ("from_location_id", line.get("to_location_id")),
                    ("to_location_id", line.get("from_location_id")),
                    ("quantity_scaled", line["quantity_scaled"]),
                    ("quantity_precision", line["quantity_precision"]),
                )
            ):
                raise PlatformError(
                    f"Compensating movement line {line['line_number']} must exactly swap locations and quantity."
                )

    def _reversal(self, reversal_id: str) -> dict[str, Any]:
        return self._one(
            """SELECT r.*,d.valuation_number original_valuation_number,d.total_value_minor original_total_value_minor,
            d.movement_id original_movement_id,d.finance_entry_id original_finance_entry_id,
            om.movement_number original_movement_number,om.movement_type original_movement_type,
            rm.movement_number reversal_movement_number,rm.movement_type reversal_movement_type,
            rm.status reversal_movement_status,o.organization_code,e.entity_code,p.name period_name,
            f.entry_number finance_entry_number,f.status finance_entry_status
            FROM reconforge.inventory_valuation_reversals r
            JOIN reconforge.inventory_valuation_documents d ON d.tenant_id=r.tenant_id AND d.id=r.original_valuation_document_id
            JOIN reconforge.inventory_movements om ON om.tenant_id=d.tenant_id AND om.id=d.movement_id
            JOIN reconforge.inventory_movements rm ON rm.tenant_id=r.tenant_id AND rm.id=r.reversal_movement_id
            JOIN reconforge.organizations o ON o.tenant_id=r.tenant_id AND o.id=r.organization_id
            JOIN reconforge.legal_entities e ON e.tenant_id=r.tenant_id AND e.id=r.legal_entity_id
            JOIN reconforge.fiscal_periods p ON p.tenant_id=r.tenant_id AND p.id=r.period_id
            LEFT JOIN reconforge.finance_entries f ON f.tenant_id=r.tenant_id AND f.id=r.finance_entry_id
            WHERE r.tenant_id=%s AND r.id=%s""",
            (self.tenant_id, clean_text(reversal_id, "Valuation reversal ID")),
            "Inventory valuation reversal was not found.",
        )

    def _public_reversal(self, reversal: Mapping[str, object], *, details: bool) -> dict[str, Any]:
        result = public_record(reversal)
        currency = self._one(
            "SELECT minor_units FROM reconforge.currencies WHERE tenant_id=%s AND code=%s",
            (self.tenant_id, reversal["currency_code"]),
            "Valuation reversal currency is unavailable.",
        )
        minor_units = int(currency["minor_units"])
        result["total_value"] = minor_to_text(int(result.pop("total_value_minor")), minor_units)
        result["original_total_value"] = minor_to_text(int(result.pop("original_total_value_minor")), minor_units)
        if details:
            rows = self.connection.execute(
                """SELECT x.*,l.line_number,l.flow_direction,l.quantity_precision,i.item_code,u.uom_code,
                lot.lot_serial_code,sd.valuation_number layer_valuation_number
                FROM reconforge.inventory_valuation_reversal_effects x
                JOIN reconforge.inventory_valuation_lines l ON l.tenant_id=x.tenant_id AND l.id=x.original_valuation_line_id
                JOIN reconforge.inventory_items i ON i.tenant_id=l.tenant_id AND i.id=l.item_id
                JOIN reconforge.inventory_units_of_measure u ON u.tenant_id=l.tenant_id AND u.id=l.uom_id
                LEFT JOIN reconforge.inventory_lots lot ON lot.tenant_id=l.tenant_id AND lot.id=l.inventory_lot_id
                JOIN reconforge.inventory_cost_layers cl ON cl.tenant_id=x.tenant_id AND cl.id=x.cost_layer_id
                JOIN reconforge.inventory_valuation_lines sl ON sl.tenant_id=cl.tenant_id AND sl.id=cl.source_valuation_line_id
                JOIN reconforge.inventory_valuation_documents sd ON sd.tenant_id=sl.tenant_id AND sd.id=sl.valuation_document_id
                WHERE x.tenant_id=%s AND x.reversal_id=%s ORDER BY l.line_number,x.effect_type,x.created_at,x.id""",
                (self.tenant_id, reversal["id"]),
            ).fetchall()
            effects = []
            for row in rows:
                item = public_record(row)
                item["quantity"] = scaled_to_text(int(item.pop("quantity_scaled")), int(item["quantity_precision"]))
                item["value"] = minor_to_text(int(item.pop("value_minor")), minor_units)
                effects.append(item)
            result["effects"] = effects
        return result

    def create_reversal(
        self,
        *,
        reversal_number: str,
        original_valuation_document_id: str,
        reversal_movement_id: str,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        actor = clean_text(actor_label, "Actor label")
        number = document_number(reversal_number, "Valuation reversal number")
        with self._transaction():
            original = self._original(original_valuation_document_id)
            if original["status"] != "Approved" or not original["finance_entry_id"]:
                raise PlatformError("Only an Approved valuation with Finance evidence can be reversed.")
            movement = self._movement(reversal_movement_id)
            self._validate_scope_and_mirror(original, movement)
            conflict = self.connection.execute(
                """SELECT 1 FROM reconforge.inventory_valuation_documents WHERE tenant_id=%s AND movement_id=%s AND status<>'Cancelled'
                UNION ALL SELECT 1 FROM reconforge.inventory_valuation_reversals WHERE tenant_id=%s AND status<>'Cancelled' AND (original_valuation_document_id=%s OR reversal_movement_id=%s) LIMIT 1""",
                (self.tenant_id, movement["id"], self.tenant_id, original["id"], movement["id"]),
            ).fetchone()
            if conflict is not None:
                raise PlatformError("Valuation or compensating movement already has an active valuation workflow.")
            reversal_id = platform_id("IVR", original["workspace_id"], number)
            row = self.connection.execute(
                """INSERT INTO reconforge.inventory_valuation_reversals(
                tenant_id,id,workspace_id,organization_id,legal_entity_id,period_id,
                original_valuation_document_id,reversal_movement_id,reversal_number,reversal_date,
                currency_code,created_by) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING row_version""",
                (
                    self.tenant_id,
                    reversal_id,
                    original["workspace_id"],
                    original["organization_id"],
                    original["legal_entity_id"],
                    movement["period_id"],
                    original["id"],
                    movement["id"],
                    number,
                    movement["movement_date"],
                    original["currency_code"],
                    actor,
                ),
            ).fetchone()
            self._event(
                actor_label=actor,
                object_id=reversal_id,
                action="inventory_valuation_reversal_draft_created",
                version=row["row_version"],
                metadata={
                    "reversal_number": number,
                    "original_valuation_document_id": original["id"],
                    "reversal_movement_id": movement["id"],
                },
            )
            return self._public_reversal(self._reversal(reversal_id), details=True)

    def cancel_reversal(self, reversal_id: str, *, reason: str, actor_label: str = "local-cli") -> dict[str, Any]:
        actor = clean_text(actor_label, "Actor label")
        cancel_reason = clean_text(reason, "Cancellation reason", maximum=500)
        selected_id = clean_text(reversal_id, "Valuation reversal ID")
        with self._transaction():
            row = self.connection.execute(
                """UPDATE reconforge.inventory_valuation_reversals SET status='Cancelled',cancelled_by=%s,
                cancelled_at=now(),cancel_reason=%s,updated_at=now(),row_version=row_version+1
                WHERE tenant_id=%s AND id=%s AND status='Draft' RETURNING row_version""",
                (actor, cancel_reason, self.tenant_id, selected_id),
            ).fetchone()
            if row is None:
                self._reversal(selected_id)
                raise PlatformError("Only Draft valuation reversals can be cancelled.")
            self._event(
                actor_label=actor,
                object_id=selected_id,
                action="inventory_valuation_reversal_cancelled",
                version=row["row_version"],
                metadata={"reason": cancel_reason},
            )
            return self._public_reversal(self._reversal(selected_id), details=True)

    def get_reversal(self, reversal_id: str, *, actor_label: str = "local-cli") -> dict[str, Any]:
        with self._transaction():
            return self._public_reversal(self._reversal(reversal_id), details=True)

    def list_reversals(
        self,
        *,
        workspace: str = "default",
        status: str = "",
        limit: int = 500,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]:
        statuses = {value.lower(): value for value in ("Draft", "Approved", "Cancelled")}
        selected = ""
        if status:
            raw = clean_text(status, "Valuation reversal status", maximum=40)
            selected = statuses.get(raw.lower(), "")
            if not selected:
                raise PlatformError("Valuation reversal status must be Draft, Approved, or Cancelled.")
        limit, offset = page(limit, offset)
        with self._transaction():
            workspace_id = self._workspace_id(workspace)
            rows = self.connection.execute(
                """SELECT id FROM reconforge.inventory_valuation_reversals WHERE tenant_id=%s AND workspace_id=%s
                AND (%s='' OR status=%s) ORDER BY reversal_date DESC,reversal_number DESC,id LIMIT %s OFFSET %s""",
                (self.tenant_id, workspace_id, selected, selected, limit, offset),
            ).fetchall()
            return [self._public_reversal(self._reversal(str(row["id"])), details=False) for row in rows]

    def summary(
        self, *, workspace: str = "default", actor_label: str = "local-cli"
    ) -> InventoryValuationReversalSummary:
        workspace_name = clean_text(workspace, "Workspace name")
        with self._transaction():
            workspace_id = self._workspace_id(workspace_name)
            row = self.connection.execute(
                """SELECT
                (SELECT COUNT(*) FROM reconforge.inventory_valuation_reversals WHERE tenant_id=%s AND workspace_id=%s AND status='Draft') drafts,
                (SELECT COUNT(*) FROM reconforge.inventory_valuation_reversals WHERE tenant_id=%s AND workspace_id=%s AND status='Approved') approved,
                (SELECT COUNT(*) FROM reconforge.inventory_valuation_reversals WHERE tenant_id=%s AND workspace_id=%s AND status='Cancelled') cancelled,
                (SELECT COUNT(*) FROM reconforge.inventory_valuation_reversal_effects x JOIN reconforge.inventory_valuation_reversals r ON r.tenant_id=x.tenant_id AND r.id=x.reversal_id WHERE r.tenant_id=%s AND r.workspace_id=%s AND r.status='Approved') effects,
                (SELECT COUNT(*) FROM reconforge.inventory_valuation_reversals r JOIN reconforge.finance_entries e ON e.tenant_id=r.tenant_id AND e.id=r.finance_entry_id WHERE r.tenant_id=%s AND r.workspace_id=%s AND r.status='Approved' AND e.status='Draft') drafts_finance""",
                (self.tenant_id, workspace_id) * 5,
            ).fetchone()
            return InventoryValuationReversalSummary(
                workspace_name,
                int(row["drafts"]),
                int(row["approved"]),
                int(row["cancelled"]),
                int(row["effects"]),
                int(row["drafts_finance"]),
            )

    def snapshot(self, *, workspace: str = "default", actor_label: str = "local-cli") -> dict[str, Any]:
        workspace_name = clean_text(workspace, "Workspace name")
        return {
            "schema_version": 1,
            "generated_at": utc_now_text(),
            "source": {
                "kind": "local-inventory-valuation-reversal",
                "local_first": True,
                "external_calls": False,
            },
            "workspace": workspace_name,
            "summary": self.summary(workspace=workspace_name, actor_label=actor_label).to_dict(),
            "reversals": self.list_reversals(workspace=workspace_name, actor_label=actor_label),
            "boundary_note": (
                "Approval requires a separately Posted exact opposite movement and creates a balanced "
                "Finance Core Draft; it validates no entry and writes to no external ERP."
            ),
        }

    def approve_reversal(self, reversal_id: str, *, reason: str, actor_label: str = "local-cli") -> dict[str, Any]:
        actor = clean_text(actor_label, "Actor label")
        approval_reason = clean_text(reason, "Approval reason", maximum=500)
        selected_id = clean_text(reversal_id, "Valuation reversal ID")
        with self._transaction():
            lock = self.connection.execute(
                "SELECT id FROM reconforge.inventory_valuation_reversals WHERE tenant_id=%s AND id=%s FOR UPDATE",
                (self.tenant_id, selected_id),
            ).fetchone()
            if lock is None:
                raise PlatformError("Inventory valuation reversal was not found.")
            reversal = self._reversal(selected_id)
            if reversal["status"] != "Draft":
                raise PlatformError("Only Draft valuation reversals can be approved.")
            if same_actor(reversal["created_by"], actor):
                raise PlatformError("Segregation of duties prevents approving your own valuation reversal.")
            original = self._original(str(reversal["original_valuation_document_id"]))
            if original["status"] != "Approved":
                raise PlatformError("Reversal approval requires the original valuation to remain Approved.")
            movement = self._movement(str(reversal["reversal_movement_id"]))
            self._validate_scope_and_mirror(original, movement)
            effects = self._prepare_effects(selected_id, original)
            total = sum(int(str(effect["value_minor"])) for effect in effects)
            if total <= 0 or total > MAX_AMOUNT_MINOR or total != int(str(original["total_value_minor"])):
                raise PlatformError("Valuation reversal effects must equal the supported original total value.")
            finance_entry_id = self._create_finance_draft(reversal, original)
            for effect in effects:
                self.connection.execute(
                    """INSERT INTO reconforge.inventory_valuation_reversal_effects(
                    tenant_id,id,reversal_id,original_valuation_line_id,original_consumption_id,cost_layer_id,
                    effect_type,quantity_scaled,value_minor) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        self.tenant_id,
                        effect["id"],
                        selected_id,
                        effect["original_valuation_line_id"],
                        effect["original_consumption_id"],
                        effect["cost_layer_id"],
                        effect["effect_type"],
                        effect["quantity_scaled"],
                        effect["value_minor"],
                    ),
                )
                query = (
                    "UPDATE reconforge.inventory_cost_layers SET "
                    "remaining_quantity_scaled=remaining_quantity_scaled+%s,"
                    "remaining_value_minor=remaining_value_minor+%s,row_version=row_version+1 "
                    "WHERE tenant_id=%s AND id=%s"
                    if effect["effect_type"] == "Restore"
                    else "UPDATE reconforge.inventory_cost_layers SET "
                    "remaining_quantity_scaled=remaining_quantity_scaled-%s,"
                    "remaining_value_minor=remaining_value_minor-%s,row_version=row_version+1 "
                    "WHERE tenant_id=%s AND id=%s"
                )
                self.connection.execute(
                    query,
                    (
                        effect["quantity_scaled"],
                        effect["value_minor"],
                        self.tenant_id,
                        effect["cost_layer_id"],
                    ),
                )
            row = self.connection.execute(
                """UPDATE reconforge.inventory_valuation_reversals SET status='Approved',total_value_minor=%s,
                finance_entry_id=%s,approved_by=%s,approved_at=now(),approval_reason=%s,updated_at=now(),
                row_version=row_version+1 WHERE tenant_id=%s AND id=%s AND status='Draft' RETURNING row_version""",
                (total, finance_entry_id, actor, approval_reason, self.tenant_id, selected_id),
            ).fetchone()
            if row is None:
                raise PlatformError("Valuation reversal changed concurrently; reload and retry.")
            self._event(
                actor_label=actor,
                object_id=selected_id,
                action="inventory_valuation_reversal_approved",
                version=row["row_version"],
                metadata={
                    "reversal_number": reversal["reversal_number"],
                    "effect_count": len(effects),
                    "total_value_minor": total,
                    "finance_entry_id": finance_entry_id,
                },
            )
            return self._public_reversal(self._reversal(selected_id), details=True)

    def _prepare_effects(self, reversal_id: str, original: Mapping[str, object]) -> list[dict[str, object]]:
        lines = self.connection.execute(
            """SELECT l.*,cl.id cost_layer_id,cl.original_quantity_scaled,cl.remaining_quantity_scaled,
            cl.original_value_minor,cl.remaining_value_minor
            FROM reconforge.inventory_valuation_lines l
            LEFT JOIN reconforge.inventory_cost_layers cl ON cl.tenant_id=l.tenant_id AND cl.source_valuation_line_id=l.id
            WHERE l.tenant_id=%s AND l.valuation_document_id=%s ORDER BY l.line_number,l.id""",
            (self.tenant_id, original["id"]),
        ).fetchall()
        consumptions = self.connection.execute(
            """SELECT c.*,l.valuation_document_id,cl.original_quantity_scaled,cl.remaining_quantity_scaled,
            cl.original_value_minor,cl.remaining_value_minor
            FROM reconforge.inventory_layer_consumptions c
            JOIN reconforge.inventory_valuation_lines l ON l.tenant_id=c.tenant_id AND l.id=c.valuation_line_id
            JOIN reconforge.inventory_cost_layers cl ON cl.tenant_id=c.tenant_id AND cl.id=c.cost_layer_id
            WHERE c.tenant_id=%s AND l.valuation_document_id=%s ORDER BY c.cost_layer_id,c.created_at,c.id""",
            (self.tenant_id, original["id"]),
        ).fetchall()
        layer_ids = sorted(
            {str(value) for row in [*lines, *consumptions] if (value := row.get("cost_layer_id")) is not None}
        )
        for layer_id in layer_ids:
            self.connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (layer_id,))
        if layer_ids:
            self.connection.execute(
                "SELECT id FROM reconforge.inventory_cost_layers WHERE tenant_id=%s AND id=ANY(%s) ORDER BY id FOR UPDATE",
                (self.tenant_id, layer_ids),
            ).fetchall()
            lines = self.connection.execute(
                """SELECT l.*,cl.id cost_layer_id,cl.original_quantity_scaled,cl.remaining_quantity_scaled,
                cl.original_value_minor,cl.remaining_value_minor
                FROM reconforge.inventory_valuation_lines l
                LEFT JOIN reconforge.inventory_cost_layers cl ON cl.tenant_id=l.tenant_id AND cl.source_valuation_line_id=l.id
                WHERE l.tenant_id=%s AND l.valuation_document_id=%s ORDER BY l.line_number,l.id""",
                (self.tenant_id, original["id"]),
            ).fetchall()
            consumptions = self.connection.execute(
                """SELECT c.*,l.valuation_document_id,cl.original_quantity_scaled,cl.remaining_quantity_scaled,
                cl.original_value_minor,cl.remaining_value_minor
                FROM reconforge.inventory_layer_consumptions c
                JOIN reconforge.inventory_valuation_lines l ON l.tenant_id=c.tenant_id AND l.id=c.valuation_line_id
                JOIN reconforge.inventory_cost_layers cl ON cl.tenant_id=c.tenant_id AND cl.id=c.cost_layer_id
                WHERE c.tenant_id=%s AND l.valuation_document_id=%s ORDER BY c.cost_layer_id,c.created_at,c.id""",
                (self.tenant_id, original["id"]),
            ).fetchall()
        effects: list[dict[str, object]] = []
        for raw in lines:
            line = dict(raw)
            if line["flow_direction"] != "Inbound":
                continue
            if not line["cost_layer_id"] or (
                int(line["remaining_quantity_scaled"]) != int(line["original_quantity_scaled"])
                or int(line["remaining_value_minor"]) != int(line["original_value_minor"])
            ):
                raise PlatformError(
                    f"Inbound layer for line {line['line_number']} is consumed; reverse dependent valuations first."
                )
            effects.append(
                {
                    "id": platform_id("IVE", reversal_id, line["id"], "Remove"),
                    "original_valuation_line_id": line["id"],
                    "original_consumption_id": None,
                    "cost_layer_id": line["cost_layer_id"],
                    "effect_type": "Remove",
                    "quantity_scaled": line["quantity_scaled"],
                    "value_minor": line["value_minor"],
                }
            )
        restored: dict[str, tuple[int, int]] = {}
        for raw in consumptions:
            consumption = dict(raw)
            layer_id = str(consumption["cost_layer_id"])
            prior_quantity, prior_value = restored.get(
                layer_id,
                (int(consumption["remaining_quantity_scaled"]), int(consumption["remaining_value_minor"])),
            )
            new_quantity = prior_quantity + int(consumption["quantity_scaled"])
            new_value = prior_value + int(consumption["value_minor"])
            if new_quantity > int(consumption["original_quantity_scaled"]) or new_value > int(
                consumption["original_value_minor"]
            ):
                raise PlatformError("Restoring the outbound valuation would overstate its FIFO layer.")
            restored[layer_id] = (new_quantity, new_value)
            effects.append(
                {
                    "id": platform_id("IVE", reversal_id, consumption["id"], "Restore"),
                    "original_valuation_line_id": consumption["valuation_line_id"],
                    "original_consumption_id": consumption["id"],
                    "cost_layer_id": consumption["cost_layer_id"],
                    "effect_type": "Restore",
                    "quantity_scaled": consumption["quantity_scaled"],
                    "value_minor": consumption["value_minor"],
                }
            )
        if not effects:
            raise PlatformError("Valuation reversal requires at least one exact layer effect.")
        return effects

    def _create_finance_draft(self, reversal: Mapping[str, object], original: Mapping[str, object]) -> str:
        original_entry = self._one(
            "SELECT * FROM reconforge.finance_entries WHERE tenant_id=%s AND id=%s",
            (self.tenant_id, original["finance_entry_id"]),
            "Original Finance Core entry was not found.",
        )
        lines = self.connection.execute(
            "SELECT * FROM reconforge.finance_entry_lines WHERE tenant_id=%s AND entry_id=%s ORDER BY line_number,id",
            (self.tenant_id, original_entry["id"]),
        ).fetchall()
        if len(lines) < 2:
            raise PlatformError("Original Finance Core entry is missing balanced line evidence.")
        total = sum(int(line["credit_minor"]) for line in lines)
        if total <= 0 or total != sum(int(line["debit_minor"]) for line in lines):
            raise PlatformError("Original Finance Core entry cannot produce a balanced reversal Draft.")
        number = f"IVR-{reversal['reversal_number']}"
        if len(number) > 64:
            number = "IVR-" + sha256(str(reversal["id"]).encode()).hexdigest()[:16].upper()
        if self.connection.execute(
            "SELECT 1 FROM reconforge.finance_entries WHERE tenant_id=%s AND workspace_id=%s AND entry_number=%s",
            (self.tenant_id, reversal["workspace_id"], number),
        ).fetchone():
            raise PlatformError("Generated reversal Finance Core entry number already exists.")
        entry_id = platform_id("FEN", reversal["workspace_id"], number)
        self.connection.execute(
            """INSERT INTO reconforge.finance_entries(
            tenant_id,id,workspace_id,journal_id,organization_code,entity_code,period_id,entry_number,
            posting_date,description,external_reference,source_type,status,currency_code,total_debit_minor,
            total_credit_minor,created_by,created_at,updated_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
            'Generated','Draft',%s,%s,%s,%s,%s,%s)""",
            (
                self.tenant_id,
                entry_id,
                reversal["workspace_id"],
                original_entry["journal_id"],
                original_entry["organization_code"],
                original_entry["entity_code"],
                reversal["period_id"],
                number,
                reversal["reversal_date"],
                f"FIFO valuation reversal {reversal['reversal_number']}",
                f"Reverses valuation {original['valuation_number']}",
                reversal["currency_code"],
                total,
                total,
                reversal["created_by"],
                utc_now_text(),
                utc_now_text(),
            ),
        )
        for line in lines:
            line_id = platform_id("FEL", entry_id, line["line_number"])
            self.connection.execute(
                """INSERT INTO reconforge.finance_entry_lines(
                tenant_id,id,entry_id,line_number,account_id,description,debit_minor,credit_minor,currency_code)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    self.tenant_id,
                    line_id,
                    entry_id,
                    line["line_number"],
                    line["account_id"],
                    f"Reverse FIFO valuation {original['valuation_number']}",
                    line["credit_minor"],
                    line["debit_minor"],
                    line["currency_code"],
                ),
            )
            dimensions = self.connection.execute(
                "SELECT dimension_id,dimension_value_id FROM reconforge.finance_entry_line_dimensions WHERE tenant_id=%s AND entry_line_id=%s ORDER BY dimension_id",
                (self.tenant_id, line["id"]),
            ).fetchall()
            for dimension in dimensions:
                self.connection.execute(
                    "INSERT INTO reconforge.finance_entry_line_dimensions(tenant_id,entry_line_id,dimension_id,dimension_value_id) VALUES(%s,%s,%s,%s)",
                    (self.tenant_id, line_id, dimension["dimension_id"], dimension["dimension_value_id"]),
                )
        return entry_id
