"""PostgreSQL storage foundation for governed FIFO inventory valuation.

The eleven-operation adapter is intentionally added only after the aggregate
and database invariants can be migrated and rolled back independently.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from decimal import ROUND_HALF_EVEN, Decimal
from hashlib import sha256
from typing import Any

from reconforge.application.inventory_valuation import InventoryValuationSummary
from reconforge.auth.rbac import same_actor
from reconforge.infrastructure.postgres import set_local_tenant_scope, validate_tenant_id
from reconforge.infrastructure.postgres_domain import PostgresAuditEventRepository
from reconforge.io.persisted import PersistedJsonError, encode_postgres_outbox_payload
from reconforge.platform.common import PlatformError, platform_id
from reconforge.platform.inventory_values import (
    MAX_AMOUNT_MINOR,
    amount_to_minor,
    choice,
    clean_text,
    code,
    document_number,
    iso_date,
    minor_to_text,
    page,
    public_record,
    scaled_to_text,
)
from reconforge.utils.time import utc_now_text

VALUATION_STATUSES = ("Draft", "Approved", "Cancelled")
MAX_VALUATION_LINES = 1_000


class PostgresInventoryValuationError(RuntimeError):
    """Safe PostgreSQL inventory valuation failure."""


POSTGRES_INVENTORY_VALUATION_SCHEMA_SQL = r"""
CREATE TABLE IF NOT EXISTS reconforge.inventory_valuation_policies (
 tenant_id TEXT NOT NULL,id TEXT NOT NULL,workspace_id TEXT NOT NULL,
 organization_id TEXT NOT NULL,legal_entity_id TEXT NOT NULL,policy_code TEXT NOT NULL,
 costing_method TEXT NOT NULL DEFAULT 'FIFO' CHECK(costing_method='FIFO'),currency_code TEXT NOT NULL,
 finance_journal_id TEXT NOT NULL,receipt_clearing_account_id TEXT NOT NULL,cogs_account_id TEXT NOT NULL,
 adjustment_account_id TEXT NOT NULL,active BOOLEAN NOT NULL DEFAULT TRUE,created_by TEXT NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 row_version BIGINT NOT NULL DEFAULT 1 CHECK(row_version>0),
 PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,workspace_id,organization_id,legal_entity_id,policy_code),
 FOREIGN KEY(tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id) ON DELETE CASCADE,
 FOREIGN KEY(tenant_id,organization_id) REFERENCES reconforge.organizations(tenant_id,id) ON DELETE RESTRICT,
 FOREIGN KEY(tenant_id,legal_entity_id) REFERENCES reconforge.legal_entities(tenant_id,id) ON DELETE RESTRICT,
 FOREIGN KEY(tenant_id,currency_code) REFERENCES reconforge.currencies(tenant_id,code) ON DELETE RESTRICT,
 FOREIGN KEY(tenant_id,finance_journal_id) REFERENCES reconforge.finance_journals(tenant_id,id) ON DELETE RESTRICT,
 FOREIGN KEY(tenant_id,receipt_clearing_account_id) REFERENCES reconforge.finance_accounts(tenant_id,id) ON DELETE RESTRICT,
 FOREIGN KEY(tenant_id,cogs_account_id) REFERENCES reconforge.finance_accounts(tenant_id,id) ON DELETE RESTRICT,
 FOREIGN KEY(tenant_id,adjustment_account_id) REFERENCES reconforge.finance_accounts(tenant_id,id) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS reconforge.inventory_valuation_documents (
 tenant_id TEXT NOT NULL,id TEXT NOT NULL,workspace_id TEXT NOT NULL,organization_id TEXT NOT NULL,
 legal_entity_id TEXT NOT NULL,period_id TEXT NOT NULL,movement_id TEXT NOT NULL,policy_id TEXT NOT NULL,
 valuation_number TEXT NOT NULL,valuation_date DATE NOT NULL,currency_code TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'Draft' CHECK(status IN('Draft','Approved','Cancelled')),
 total_value_minor BIGINT NOT NULL DEFAULT 0 CHECK(total_value_minor>=0),finance_entry_id TEXT,
 created_by TEXT NOT NULL,approved_by TEXT NOT NULL DEFAULT '',approved_at TIMESTAMPTZ,
 approval_reason TEXT NOT NULL DEFAULT '',cancelled_by TEXT NOT NULL DEFAULT '',cancelled_at TIMESTAMPTZ,
 cancel_reason TEXT NOT NULL DEFAULT '',created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),row_version BIGINT NOT NULL DEFAULT 1 CHECK(row_version>0),
 PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,workspace_id,valuation_number),UNIQUE(tenant_id,finance_entry_id),
 FOREIGN KEY(tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id) ON DELETE CASCADE,
 FOREIGN KEY(tenant_id,organization_id) REFERENCES reconforge.organizations(tenant_id,id) ON DELETE RESTRICT,
 FOREIGN KEY(tenant_id,legal_entity_id) REFERENCES reconforge.legal_entities(tenant_id,id) ON DELETE RESTRICT,
 FOREIGN KEY(tenant_id,period_id) REFERENCES reconforge.fiscal_periods(tenant_id,id) ON DELETE RESTRICT,
 FOREIGN KEY(tenant_id,movement_id) REFERENCES reconforge.inventory_movements(tenant_id,id) ON DELETE RESTRICT,
 FOREIGN KEY(tenant_id,policy_id) REFERENCES reconforge.inventory_valuation_policies(tenant_id,id) ON DELETE RESTRICT,
 FOREIGN KEY(tenant_id,currency_code) REFERENCES reconforge.currencies(tenant_id,code) ON DELETE RESTRICT,
 FOREIGN KEY(tenant_id,finance_entry_id) REFERENCES reconforge.finance_entries(tenant_id,id) ON DELETE RESTRICT,
 CHECK(status='Draft' OR (status='Approved' AND total_value_minor>0 AND finance_entry_id IS NOT NULL) OR status='Cancelled')
);
CREATE UNIQUE INDEX IF NOT EXISTS inventory_valuation_active_movement_idx
 ON reconforge.inventory_valuation_documents(tenant_id,movement_id) WHERE status<>'Cancelled';
CREATE TABLE IF NOT EXISTS reconforge.inventory_valuation_input_costs (
 tenant_id TEXT NOT NULL,id TEXT NOT NULL,valuation_document_id TEXT NOT NULL,movement_line_id TEXT NOT NULL,
 total_cost_minor BIGINT NOT NULL CHECK(total_cost_minor>0),created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,valuation_document_id,movement_line_id),
 FOREIGN KEY(tenant_id,valuation_document_id) REFERENCES reconforge.inventory_valuation_documents(tenant_id,id) ON DELETE CASCADE,
 FOREIGN KEY(tenant_id,movement_line_id) REFERENCES reconforge.inventory_movement_lines(tenant_id,id) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS reconforge.inventory_valuation_lines (
 tenant_id TEXT NOT NULL,id TEXT NOT NULL,valuation_document_id TEXT NOT NULL,movement_line_id TEXT NOT NULL,
 line_number INTEGER NOT NULL CHECK(line_number>0),flow_direction TEXT NOT NULL CHECK(flow_direction IN('Inbound','Outbound')),
 item_id TEXT NOT NULL,uom_id TEXT NOT NULL,inventory_lot_id TEXT,quantity_scaled BIGINT NOT NULL CHECK(quantity_scaled>0),
 quantity_precision INTEGER NOT NULL CHECK(quantity_precision BETWEEN 0 AND 6),value_minor BIGINT NOT NULL CHECK(value_minor>0),
 inventory_account_id TEXT NOT NULL,offset_account_id TEXT NOT NULL,created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,valuation_document_id,line_number),UNIQUE(tenant_id,valuation_document_id,movement_line_id),
 FOREIGN KEY(tenant_id,valuation_document_id) REFERENCES reconforge.inventory_valuation_documents(tenant_id,id) ON DELETE CASCADE,
 FOREIGN KEY(tenant_id,movement_line_id) REFERENCES reconforge.inventory_movement_lines(tenant_id,id) ON DELETE RESTRICT,
 FOREIGN KEY(tenant_id,item_id) REFERENCES reconforge.inventory_items(tenant_id,id) ON DELETE RESTRICT,
 FOREIGN KEY(tenant_id,uom_id) REFERENCES reconforge.inventory_units_of_measure(tenant_id,id) ON DELETE RESTRICT,
 FOREIGN KEY(tenant_id,inventory_lot_id) REFERENCES reconforge.inventory_lots(tenant_id,id) ON DELETE RESTRICT,
 FOREIGN KEY(tenant_id,inventory_account_id) REFERENCES reconforge.finance_accounts(tenant_id,id) ON DELETE RESTRICT,
 FOREIGN KEY(tenant_id,offset_account_id) REFERENCES reconforge.finance_accounts(tenant_id,id) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS reconforge.inventory_cost_layers (
 tenant_id TEXT NOT NULL,id TEXT NOT NULL,workspace_id TEXT NOT NULL,source_valuation_line_id TEXT NOT NULL,
 legal_entity_id TEXT NOT NULL,item_id TEXT NOT NULL,uom_id TEXT NOT NULL,inventory_lot_id TEXT,
 quantity_precision INTEGER NOT NULL CHECK(quantity_precision BETWEEN 0 AND 6),
 original_quantity_scaled BIGINT NOT NULL CHECK(original_quantity_scaled>0),remaining_quantity_scaled BIGINT NOT NULL,
 original_value_minor BIGINT NOT NULL CHECK(original_value_minor>0),remaining_value_minor BIGINT NOT NULL,
 currency_code TEXT NOT NULL,created_at TIMESTAMPTZ NOT NULL DEFAULT now(),row_version BIGINT NOT NULL DEFAULT 1,
 PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,source_valuation_line_id),
 FOREIGN KEY(tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id) ON DELETE CASCADE,
 FOREIGN KEY(tenant_id,source_valuation_line_id) REFERENCES reconforge.inventory_valuation_lines(tenant_id,id) ON DELETE RESTRICT,
 FOREIGN KEY(tenant_id,legal_entity_id) REFERENCES reconforge.legal_entities(tenant_id,id) ON DELETE RESTRICT,
 FOREIGN KEY(tenant_id,item_id) REFERENCES reconforge.inventory_items(tenant_id,id) ON DELETE RESTRICT,
 FOREIGN KEY(tenant_id,uom_id) REFERENCES reconforge.inventory_units_of_measure(tenant_id,id) ON DELETE RESTRICT,
 FOREIGN KEY(tenant_id,inventory_lot_id) REFERENCES reconforge.inventory_lots(tenant_id,id) ON DELETE RESTRICT,
 FOREIGN KEY(tenant_id,currency_code) REFERENCES reconforge.currencies(tenant_id,code) ON DELETE RESTRICT,
 CHECK(remaining_quantity_scaled BETWEEN 0 AND original_quantity_scaled),
 CHECK(remaining_value_minor BETWEEN 0 AND original_value_minor),
 CHECK((remaining_quantity_scaled=0 AND remaining_value_minor=0) OR (remaining_quantity_scaled>0 AND remaining_value_minor>0))
);
CREATE TABLE IF NOT EXISTS reconforge.inventory_layer_consumptions (
 tenant_id TEXT NOT NULL,id TEXT NOT NULL,workspace_id TEXT NOT NULL,valuation_line_id TEXT NOT NULL,
 cost_layer_id TEXT NOT NULL,quantity_scaled BIGINT NOT NULL CHECK(quantity_scaled>0),
 value_minor BIGINT NOT NULL CHECK(value_minor>0),created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,valuation_line_id,cost_layer_id),
 FOREIGN KEY(tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id) ON DELETE CASCADE,
 FOREIGN KEY(tenant_id,valuation_line_id) REFERENCES reconforge.inventory_valuation_lines(tenant_id,id) ON DELETE RESTRICT,
 FOREIGN KEY(tenant_id,cost_layer_id) REFERENCES reconforge.inventory_cost_layers(tenant_id,id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS inventory_valuation_documents_scope_idx ON reconforge.inventory_valuation_documents(tenant_id,workspace_id,status,valuation_date,id);
CREATE INDEX IF NOT EXISTS inventory_cost_layers_fifo_idx ON reconforge.inventory_cost_layers(tenant_id,workspace_id,legal_entity_id,item_id,inventory_lot_id,created_at,id) WHERE remaining_quantity_scaled>0;

CREATE OR REPLACE FUNCTION reconforge.inventory_valuation_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE document_status TEXT;
BEGIN
 IF TG_TABLE_NAME='inventory_valuation_documents' THEN
  IF TG_OP='INSERT' AND (NEW.status<>'Draft' OR NEW.total_value_minor<>0 OR NEW.finance_entry_id IS NOT NULL) THEN RAISE EXCEPTION 'inventory valuations must be created as empty Draft documents'; END IF;
  IF TG_OP='UPDATE' AND NEW.status<>OLD.status AND NOT ((OLD.status='Draft' AND NEW.status='Approved') OR (OLD.status='Draft' AND NEW.status='Cancelled')) THEN RAISE EXCEPTION 'invalid inventory valuation status transition'; END IF;
  IF TG_OP='UPDATE' AND OLD.status='Draft' AND NEW.status='Approved' AND (NEW.approved_by='' OR NEW.approved_at IS NULL OR NEW.approval_reason='' OR NEW.total_value_minor<=0 OR NEW.finance_entry_id IS NULL OR NOT EXISTS(SELECT 1 FROM reconforge.inventory_movements m WHERE m.tenant_id=OLD.tenant_id AND m.id=OLD.movement_id AND m.status='Posted') OR NEW.total_value_minor<>(SELECT COALESCE(SUM(value_minor),0) FROM reconforge.inventory_valuation_lines WHERE tenant_id=OLD.tenant_id AND valuation_document_id=OLD.id) OR NOT EXISTS(SELECT 1 FROM reconforge.finance_entries e WHERE e.tenant_id=OLD.tenant_id AND e.id=NEW.finance_entry_id AND e.status IN('Draft','Validated') AND e.currency_code=NEW.currency_code AND e.total_debit_minor=NEW.total_value_minor AND e.total_credit_minor=NEW.total_value_minor) OR EXISTS(SELECT 1 FROM reconforge.inventory_valuation_lines v WHERE v.tenant_id=OLD.tenant_id AND v.valuation_document_id=OLD.id AND ((v.flow_direction='Inbound' AND NOT EXISTS(SELECT 1 FROM reconforge.inventory_cost_layers l WHERE l.tenant_id=v.tenant_id AND l.source_valuation_line_id=v.id AND l.original_quantity_scaled=v.quantity_scaled AND l.original_value_minor=v.value_minor)) OR (v.flow_direction='Outbound' AND (v.quantity_scaled<>(SELECT COALESCE(SUM(c.quantity_scaled),0) FROM reconforge.inventory_layer_consumptions c WHERE c.tenant_id=v.tenant_id AND c.valuation_line_id=v.id) OR v.value_minor<>(SELECT COALESCE(SUM(c.value_minor),0) FROM reconforge.inventory_layer_consumptions c WHERE c.tenant_id=v.tenant_id AND c.valuation_line_id=v.id)))))) THEN RAISE EXCEPTION 'inventory valuation approval requires complete layers consumptions and balanced finance draft'; END IF;
  IF TG_OP='UPDATE' AND OLD.status='Draft' AND NEW.status='Cancelled' AND (NEW.cancelled_by='' OR NEW.cancelled_at IS NULL OR NEW.cancel_reason='') THEN RAISE EXCEPTION 'cancelling an inventory valuation requires actor timestamp and reason'; END IF;
  IF TG_OP='UPDATE' AND OLD.status<>'Draft' AND (NEW.workspace_id,NEW.organization_id,NEW.legal_entity_id,NEW.period_id,NEW.movement_id,NEW.policy_id,NEW.valuation_number,NEW.valuation_date,NEW.currency_code,NEW.created_by,NEW.created_at,NEW.approved_by,NEW.approved_at,NEW.approval_reason,NEW.total_value_minor,NEW.finance_entry_id,NEW.cancelled_by,NEW.cancelled_at,NEW.cancel_reason) IS DISTINCT FROM (OLD.workspace_id,OLD.organization_id,OLD.legal_entity_id,OLD.period_id,OLD.movement_id,OLD.policy_id,OLD.valuation_number,OLD.valuation_date,OLD.currency_code,OLD.created_by,OLD.created_at,OLD.approved_by,OLD.approved_at,OLD.approval_reason,OLD.total_value_minor,OLD.finance_entry_id,OLD.cancelled_by,OLD.cancelled_at,OLD.cancel_reason) THEN RAISE EXCEPTION 'final inventory valuation headers and lifecycle metadata are immutable'; END IF;
  IF TG_OP='DELETE' AND OLD.status<>'Draft' THEN RAISE EXCEPTION 'approved inventory valuations cannot be deleted'; END IF;
  IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;
 END IF;
 IF TG_TABLE_NAME='inventory_valuation_lines' AND TG_OP='UPDATE' THEN RAISE EXCEPTION 'inventory valuation lines are immutable'; END IF;
 IF TG_OP='DELETE' THEN SELECT status INTO document_status FROM reconforge.inventory_valuation_documents WHERE tenant_id=OLD.tenant_id AND id=OLD.valuation_document_id; ELSE SELECT status INTO document_status FROM reconforge.inventory_valuation_documents WHERE tenant_id=NEW.tenant_id AND id=NEW.valuation_document_id; END IF;
 IF document_status IS DISTINCT FROM 'Draft' THEN RAISE EXCEPTION 'approved inventory valuation details are immutable'; END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS inventory_valuation_documents_guard ON reconforge.inventory_valuation_documents;
CREATE TRIGGER inventory_valuation_documents_guard BEFORE INSERT OR UPDATE OR DELETE ON reconforge.inventory_valuation_documents FOR EACH ROW EXECUTE FUNCTION reconforge.inventory_valuation_guard();
DROP TRIGGER IF EXISTS inventory_valuation_input_costs_guard ON reconforge.inventory_valuation_input_costs;
CREATE TRIGGER inventory_valuation_input_costs_guard BEFORE INSERT OR UPDATE OR DELETE ON reconforge.inventory_valuation_input_costs FOR EACH ROW EXECUTE FUNCTION reconforge.inventory_valuation_guard();
DROP TRIGGER IF EXISTS inventory_valuation_lines_guard ON reconforge.inventory_valuation_lines;
CREATE TRIGGER inventory_valuation_lines_guard BEFORE INSERT OR UPDATE OR DELETE ON reconforge.inventory_valuation_lines FOR EACH ROW EXECUTE FUNCTION reconforge.inventory_valuation_guard();

CREATE OR REPLACE FUNCTION reconforge.inventory_cost_layer_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'inventory cost layers cannot be deleted'; END IF;
 IF TG_OP='INSERT' THEN
  IF NOT EXISTS(SELECT 1 FROM reconforge.inventory_valuation_lines v JOIN reconforge.inventory_valuation_documents d ON d.tenant_id=v.tenant_id AND d.id=v.valuation_document_id WHERE v.tenant_id=NEW.tenant_id AND v.id=NEW.source_valuation_line_id AND v.flow_direction='Inbound' AND d.status='Draft') THEN RAISE EXCEPTION 'inventory cost layers require an inbound Draft valuation line'; END IF;
  RETURN NEW;
 END IF;
 IF (NEW.source_valuation_line_id,NEW.legal_entity_id,NEW.item_id,NEW.uom_id,NEW.inventory_lot_id,NEW.quantity_precision,NEW.original_quantity_scaled,NEW.original_value_minor,NEW.currency_code,NEW.created_at) IS DISTINCT FROM (OLD.source_valuation_line_id,OLD.legal_entity_id,OLD.item_id,OLD.uom_id,OLD.inventory_lot_id,OLD.quantity_precision,OLD.original_quantity_scaled,OLD.original_value_minor,OLD.currency_code,OLD.created_at) THEN RAISE EXCEPTION 'inventory cost layer identity is immutable'; END IF;
 IF NEW.remaining_quantity_scaled>OLD.remaining_quantity_scaled OR NEW.remaining_value_minor>OLD.remaining_value_minor OR NEW.remaining_quantity_scaled<>OLD.original_quantity_scaled-(SELECT COALESCE(SUM(quantity_scaled),0) FROM reconforge.inventory_layer_consumptions WHERE tenant_id=OLD.tenant_id AND cost_layer_id=OLD.id) OR NEW.remaining_value_minor<>OLD.original_value_minor-(SELECT COALESCE(SUM(value_minor),0) FROM reconforge.inventory_layer_consumptions WHERE tenant_id=OLD.tenant_id AND cost_layer_id=OLD.id) THEN RAISE EXCEPTION 'inventory cost layer balances must equal immutable consumptions'; END IF;
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS inventory_cost_layers_guard ON reconforge.inventory_cost_layers;
CREATE TRIGGER inventory_cost_layers_guard BEFORE INSERT OR UPDATE OR DELETE ON reconforge.inventory_cost_layers FOR EACH ROW EXECUTE FUNCTION reconforge.inventory_cost_layer_guard();

CREATE OR REPLACE FUNCTION reconforge.inventory_layer_consumption_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='INSERT' AND EXISTS(SELECT 1 FROM reconforge.inventory_valuation_lines v JOIN reconforge.inventory_valuation_documents d ON d.tenant_id=v.tenant_id AND d.id=v.valuation_document_id WHERE v.tenant_id=NEW.tenant_id AND v.id=NEW.valuation_line_id AND v.flow_direction='Outbound' AND d.status='Draft') THEN RETURN NEW; END IF;
 RAISE EXCEPTION 'inventory layer consumptions are immutable and require an outbound Draft valuation line';
END $$;
DROP TRIGGER IF EXISTS inventory_layer_consumptions_guard ON reconforge.inventory_layer_consumptions;
CREATE TRIGGER inventory_layer_consumptions_guard BEFORE INSERT OR UPDATE OR DELETE ON reconforge.inventory_layer_consumptions FOR EACH ROW EXECUTE FUNCTION reconforge.inventory_layer_consumption_guard();

DO $rls$ DECLARE table_name TEXT; BEGIN
 FOREACH table_name IN ARRAY ARRAY['inventory_valuation_policies','inventory_valuation_documents','inventory_valuation_input_costs','inventory_valuation_lines','inventory_cost_layers','inventory_layer_consumptions'] LOOP
  EXECUTE format('ALTER TABLE reconforge.%I ENABLE ROW LEVEL SECURITY',table_name); EXECUTE format('ALTER TABLE reconforge.%I FORCE ROW LEVEL SECURITY',table_name);
  EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON reconforge.%I',table_name);
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname='reconforge' AND tablename=table_name AND policyname='tenant_scope') THEN
   EXECUTE format('CREATE POLICY tenant_isolation ON reconforge.%I USING (tenant_id=current_setting(''app.tenant_id'',true)) WITH CHECK (tenant_id=current_setting(''app.tenant_id'',true))',table_name);
  END IF;
 END LOOP;
END $rls$;
"""


class PostgresInventoryValuationRepository:
    """Tenant-scoped PostgreSQL FIFO valuation adapter (approval follows)."""

    def __init__(self, connection: Any, tenant_id: str) -> None:
        self.connection = connection
        self.tenant_id = validate_tenant_id(tenant_id)

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        try:
            with self.connection.transaction():
                set_local_tenant_scope(self.connection, self.tenant_id)
                yield
        except (PlatformError, PostgresInventoryValuationError):
            raise
        except Exception as exc:
            raise PostgresInventoryValuationError("PostgreSQL inventory valuation operation failed.") from exc

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
            raise PlatformError("Inventory valuation workspace was not found.")
        return str(row["id"])

    def _reversal_schema_available(self) -> bool:
        row = self.connection.execute(
            "SELECT to_regclass('reconforge.inventory_valuation_reversals') reversal_table"
        ).fetchone()
        return row is not None and row["reversal_table"] is not None

    def _active_reversal_movement(self, movement_id: object) -> bool:
        if not self._reversal_schema_available():
            return False
        return (
            self.connection.execute(
                "SELECT 1 FROM reconforge.inventory_valuation_reversals WHERE tenant_id=%s AND reversal_movement_id=%s AND status<>'Cancelled' LIMIT 1",
                (self.tenant_id, movement_id),
            ).fetchone()
            is not None
        )

    def _organization(self, workspace_id: str, organization_code: str) -> dict[str, Any]:
        return self._one(
            """SELECT o.* FROM reconforge.organizations o JOIN reconforge.master_data_workspace_organizations w ON w.tenant_id=o.tenant_id AND w.organization_id=o.id WHERE o.tenant_id=%s AND w.workspace_id=%s AND o.organization_code=%s AND o.active=TRUE""",
            (self.tenant_id, workspace_id, code(organization_code, "Organization code")),
            "Inventory valuation requires an active organization in this workspace.",
        )

    def _entity(self, organization_id: str, entity_code: str) -> dict[str, Any]:
        return self._one(
            "SELECT * FROM reconforge.legal_entities WHERE tenant_id=%s AND organization_id=%s AND entity_code=%s AND active=TRUE",
            (self.tenant_id, organization_id, code(entity_code, "Entity code")),
            "Inventory valuation requires an active legal entity.",
        )

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
            raise PostgresInventoryValuationError("Inventory valuation event payload is invalid.") from exc
        self.connection.execute(
            "INSERT INTO reconforge.outbox_events(tenant_id,event_id,event_type,aggregate_type,aggregate_id,payload) VALUES(%s,%s,%s,%s,%s,CAST(%s AS jsonb)) ON CONFLICT(tenant_id,event_id) DO NOTHING",
            (self.tenant_id, platform_id("OBX", action, object_id, version), action, object_type, object_id, payload),
        )
        PostgresAuditEventRepository(self.connection, self.tenant_id).append(
            actor_label=clean_text(actor_label, "Actor label"),
            object_type=object_type,
            object_id=object_id,
            action=action,
            metadata=metadata,
        )

    def _policy(self, policy_id: str) -> dict[str, Any]:
        return self._one(
            """SELECT p.*,o.organization_code,e.entity_code,j.journal_code,j.chart_id,j.active journal_active,j.currency_code journal_currency_code,
          ra.account_code receipt_clearing_account_code,ra.active receipt_account_active,ra.allow_posting receipt_account_allow_posting,
          ca.account_code cogs_account_code,ca.active cogs_account_active,ca.allow_posting cogs_account_allow_posting,
          aa.account_code adjustment_account_code,aa.active adjustment_account_active,aa.allow_posting adjustment_account_allow_posting
          FROM reconforge.inventory_valuation_policies p JOIN reconforge.organizations o ON o.tenant_id=p.tenant_id AND o.id=p.organization_id
          JOIN reconforge.legal_entities e ON e.tenant_id=p.tenant_id AND e.id=p.legal_entity_id
          JOIN reconforge.finance_journals j ON j.tenant_id=p.tenant_id AND j.id=p.finance_journal_id
          JOIN reconforge.finance_accounts ra ON ra.tenant_id=p.tenant_id AND ra.id=p.receipt_clearing_account_id
          JOIN reconforge.finance_accounts ca ON ca.tenant_id=p.tenant_id AND ca.id=p.cogs_account_id
          JOIN reconforge.finance_accounts aa ON aa.tenant_id=p.tenant_id AND aa.id=p.adjustment_account_id
          WHERE p.tenant_id=%s AND p.id=%s""",
            (self.tenant_id, clean_text(policy_id, "Valuation policy ID")),
            "Inventory valuation policy not found.",
        )

    @staticmethod
    def _public_policy(policy: Mapping[str, object]) -> dict[str, Any]:
        result = public_record(policy)
        for field in (
            "chart_id",
            "journal_active",
            "journal_currency_code",
            "receipt_account_active",
            "receipt_account_allow_posting",
            "cogs_account_active",
            "cogs_account_allow_posting",
            "adjustment_account_active",
            "adjustment_account_allow_posting",
        ):
            result.pop(field, None)
        return result

    def upsert_policy(
        self,
        *,
        policy_code: str,
        organization_code: str,
        entity_code: str,
        journal_code: str,
        receipt_clearing_account_code: str,
        cogs_account_code: str,
        adjustment_account_code: str,
        workspace: str = "default",
        active: bool = True,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        selected_code = code(policy_code, "Valuation policy code")
        with self._transaction():
            workspace_id = self._workspace_id(workspace)
            organization = self._organization(workspace_id, organization_code)
            entity = self._entity(str(organization["id"]), entity_code)
            journal = self._one(
                """SELECT j.*,c.active chart_active FROM reconforge.finance_journals j JOIN reconforge.finance_charts c ON c.tenant_id=j.tenant_id AND c.id=j.chart_id WHERE j.tenant_id=%s AND j.workspace_id=%s AND j.organization_code=%s AND j.journal_code=%s AND j.active=TRUE AND c.active=TRUE""",
                (self.tenant_id, workspace_id, organization["organization_code"], code(journal_code, "Journal code")),
                "Inventory valuation requires an active Finance Core journal and chart.",
            )
            if journal["currency_code"] != entity["currency_code"]:
                raise PlatformError("Valuation journal and legal-entity currencies must match.")
            required = self.connection.execute(
                "SELECT COUNT(*) total FROM reconforge.finance_dimensions WHERE tenant_id=%s AND workspace_id=%s AND required_on_entries=TRUE AND (organization_code='' OR organization_code=%s)",
                (self.tenant_id, workspace_id, organization["organization_code"]),
            ).fetchone()
            if int(required["total"]):
                raise PlatformError("Inventory valuation does not yet support required Finance Core dimensions.")
            accounts = []
            for raw, label in (
                (receipt_clearing_account_code, "Receipt clearing account"),
                (cogs_account_code, "COGS account"),
                (adjustment_account_code, "Adjustment account"),
            ):
                accounts.append(
                    self._one(
                        "SELECT * FROM reconforge.finance_accounts WHERE tenant_id=%s AND chart_id=%s AND account_code=%s AND active=TRUE AND allow_posting=TRUE",
                        (self.tenant_id, journal["chart_id"], code(raw, label)),
                        f"{label} must be active and posting-enabled.",
                    )
                )
            policy_id = platform_id("IVP", workspace_id, organization["id"], entity["id"], selected_code)
            existing = self.connection.execute(
                "SELECT * FROM reconforge.inventory_valuation_policies WHERE tenant_id=%s AND id=%s FOR UPDATE",
                (self.tenant_id, policy_id),
            ).fetchone()
            if (
                existing is not None
                and self.connection.execute(
                    "SELECT 1 FROM reconforge.inventory_valuation_documents WHERE tenant_id=%s AND policy_id=%s AND status='Approved' LIMIT 1",
                    (self.tenant_id, policy_id),
                ).fetchone()
                is not None
            ):
                protected = (
                    entity["currency_code"],
                    journal["id"],
                    accounts[0]["id"],
                    accounts[1]["id"],
                    accounts[2]["id"],
                )
                if (
                    tuple(
                        existing[field]
                        for field in (
                            "currency_code",
                            "finance_journal_id",
                            "receipt_clearing_account_id",
                            "cogs_account_id",
                            "adjustment_account_id",
                        )
                    )
                    != protected
                ):
                    raise PlatformError(
                        "A valuation policy referenced by Approved documents cannot change its financial setup."
                    )
            self.connection.execute(
                """INSERT INTO reconforge.inventory_valuation_policies(tenant_id,id,workspace_id,organization_id,legal_entity_id,policy_code,costing_method,currency_code,finance_journal_id,receipt_clearing_account_id,cogs_account_id,adjustment_account_id,active,created_by) VALUES(%s,%s,%s,%s,%s,%s,'FIFO',%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(tenant_id,workspace_id,organization_id,legal_entity_id,policy_code) DO UPDATE SET currency_code=excluded.currency_code,finance_journal_id=excluded.finance_journal_id,receipt_clearing_account_id=excluded.receipt_clearing_account_id,cogs_account_id=excluded.cogs_account_id,adjustment_account_id=excluded.adjustment_account_id,active=excluded.active,updated_at=now(),row_version=inventory_valuation_policies.row_version+1""",
                (
                    self.tenant_id,
                    policy_id,
                    workspace_id,
                    organization["id"],
                    entity["id"],
                    selected_code,
                    entity["currency_code"],
                    journal["id"],
                    accounts[0]["id"],
                    accounts[1]["id"],
                    accounts[2]["id"],
                    bool(active),
                    clean_text(actor_label, "Actor label"),
                ),
            )
            result = self._public_policy(self._policy(policy_id))
            self._event(
                actor_label=actor_label,
                object_type="inventory_valuation_policy",
                object_id=policy_id,
                action="inventory_valuation_policy_saved",
                version=result["row_version"],
                metadata={"policy_code": selected_code, "costing_method": "FIFO", "active": bool(active)},
            )
            return result

    def get_policy(self, policy_id: str, *, actor_label: str = "local-cli") -> dict[str, Any]:
        with self._transaction():
            return self._public_policy(self._policy(policy_id))

    def list_policies(
        self, *, workspace: str = "default", limit: int = 500, offset: int = 0, actor_label: str = "local-cli"
    ) -> list[dict[str, Any]]:
        limit, offset = page(limit, offset)
        with self._transaction():
            workspace_id = self._workspace_id(workspace)
            rows = self.connection.execute(
                "SELECT id FROM reconforge.inventory_valuation_policies WHERE tenant_id=%s AND workspace_id=%s ORDER BY organization_id,legal_entity_id,policy_code,id LIMIT %s OFFSET %s",
                (self.tenant_id, workspace_id, limit, offset),
            ).fetchall()
            return [self._public_policy(self._policy(str(row["id"]))) for row in rows]

    def _movement(self, movement_id: str) -> dict[str, Any]:
        return self._one(
            """SELECT m.*,o.organization_code,e.entity_code,e.currency_code entity_currency,p.status period_status,p.start_date period_start_date,p.end_date period_end_date
          FROM reconforge.inventory_movements m JOIN reconforge.organizations o ON o.tenant_id=m.tenant_id AND o.id=m.organization_id
          JOIN reconforge.legal_entities e ON e.tenant_id=m.tenant_id AND e.id=m.legal_entity_id
          JOIN reconforge.fiscal_periods p ON p.tenant_id=m.tenant_id AND p.id=m.period_id
          WHERE m.tenant_id=%s AND m.id=%s""",
            (self.tenant_id, clean_text(movement_id, "Movement ID")),
            "Inventory movement not found.",
        )

    def _movement_lines(self, movement_id: str) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """SELECT l.*,i.item_code,i.item_type,i.tracking_mode,i.inventory_account_id,
          a.account_code inventory_account_code,a.chart_id inventory_account_chart_id,a.active inventory_account_active,
          a.allow_posting inventory_account_allow_posting,u.uom_code,u.decimal_places,lot.lot_serial_code
          FROM reconforge.inventory_movement_lines l JOIN reconforge.inventory_items i ON i.tenant_id=l.tenant_id AND i.id=l.item_id
          JOIN reconforge.inventory_units_of_measure u ON u.tenant_id=l.tenant_id AND u.id=l.uom_id
          LEFT JOIN reconforge.finance_accounts a ON a.tenant_id=l.tenant_id AND a.id=i.inventory_account_id
          LEFT JOIN reconforge.inventory_lots lot ON lot.tenant_id=l.tenant_id AND lot.id=l.inventory_lot_id
          WHERE l.tenant_id=%s AND l.movement_id=%s ORDER BY l.line_number,l.id""",
            (self.tenant_id, movement_id),
        ).fetchall()
        return [dict(row) for row in rows]

    def _document(self, document_id: str) -> dict[str, Any]:
        return self._one(
            """SELECT d.*,m.movement_number,m.movement_type,m.status movement_status,o.organization_code,e.entity_code,p.name period_name,v.policy_code,v.costing_method,f.entry_number finance_entry_number,f.status finance_entry_status
          FROM reconforge.inventory_valuation_documents d JOIN reconforge.inventory_movements m ON m.tenant_id=d.tenant_id AND m.id=d.movement_id
          JOIN reconforge.organizations o ON o.tenant_id=d.tenant_id AND o.id=d.organization_id JOIN reconforge.legal_entities e ON e.tenant_id=d.tenant_id AND e.id=d.legal_entity_id
          JOIN reconforge.fiscal_periods p ON p.tenant_id=d.tenant_id AND p.id=d.period_id JOIN reconforge.inventory_valuation_policies v ON v.tenant_id=d.tenant_id AND v.id=d.policy_id
          LEFT JOIN reconforge.finance_entries f ON f.tenant_id=d.tenant_id AND f.id=d.finance_entry_id WHERE d.tenant_id=%s AND d.id=%s""",
            (self.tenant_id, clean_text(document_id, "Valuation document ID")),
            "Inventory valuation document not found.",
        )

    def _public_document(self, document: Mapping[str, object], *, details: bool) -> dict[str, Any]:
        result = public_record(document)
        currency = self._one(
            "SELECT minor_units FROM reconforge.currencies WHERE tenant_id=%s AND code=%s",
            (self.tenant_id, document["currency_code"]),
            "Valuation currency is unavailable.",
        )
        minor_units = int(currency["minor_units"])
        result["total_value"] = minor_to_text(int(result.pop("total_value_minor")), minor_units)
        if details:
            costs = self.connection.execute(
                """SELECT c.*,l.line_number FROM reconforge.inventory_valuation_input_costs c JOIN reconforge.inventory_movement_lines l ON l.tenant_id=c.tenant_id AND l.id=c.movement_line_id WHERE c.tenant_id=%s AND c.valuation_document_id=%s ORDER BY l.line_number,l.id""",
                (self.tenant_id, document["id"]),
            ).fetchall()
            result["input_costs"] = []
            for row in costs:
                value = dict(row)
                value["total_cost"] = minor_to_text(int(value.pop("total_cost_minor")), minor_units)
                result["input_costs"].append(value)
            lines = self.connection.execute(
                """SELECT v.*,m.line_number,m.item_id,i.item_code,u.uom_code,lot.lot_serial_code,ia.account_code inventory_account_code,oa.account_code offset_account_code FROM reconforge.inventory_valuation_lines v JOIN reconforge.inventory_movement_lines m ON m.tenant_id=v.tenant_id AND m.id=v.movement_line_id JOIN reconforge.inventory_items i ON i.tenant_id=v.tenant_id AND i.id=v.item_id JOIN reconforge.inventory_units_of_measure u ON u.tenant_id=v.tenant_id AND u.id=v.uom_id LEFT JOIN reconforge.inventory_lots lot ON lot.tenant_id=v.tenant_id AND lot.id=v.inventory_lot_id JOIN reconforge.finance_accounts ia ON ia.tenant_id=v.tenant_id AND ia.id=v.inventory_account_id JOIN reconforge.finance_accounts oa ON oa.tenant_id=v.tenant_id AND oa.id=v.offset_account_id WHERE v.tenant_id=%s AND v.valuation_document_id=%s ORDER BY v.line_number,v.id""",
                (self.tenant_id, document["id"]),
            ).fetchall()
            result["lines"] = []
            for row in lines:
                value = dict(row)
                value["quantity"] = scaled_to_text(int(value.pop("quantity_scaled")), int(value["quantity_precision"]))
                value["value"] = minor_to_text(int(value.pop("value_minor")), minor_units)
                result["lines"].append(value)
            consumptions = self.connection.execute(
                """SELECT c.*,v.line_number,l.id layer_id FROM reconforge.inventory_layer_consumptions c JOIN reconforge.inventory_valuation_lines v ON v.tenant_id=c.tenant_id AND v.id=c.valuation_line_id JOIN reconforge.inventory_cost_layers l ON l.tenant_id=c.tenant_id AND l.id=c.cost_layer_id WHERE c.tenant_id=%s AND v.valuation_document_id=%s ORDER BY v.line_number,l.created_at,l.id""",
                (self.tenant_id, document["id"]),
            ).fetchall()
            result["layer_consumptions"] = []
            precision_by_line = {int(line["line_number"]): int(line["quantity_precision"]) for line in lines}
            for row in consumptions:
                value = dict(row)
                value["quantity"] = scaled_to_text(
                    int(value.pop("quantity_scaled")), precision_by_line[int(value["line_number"])]
                )
                value["value"] = minor_to_text(int(value.pop("value_minor")), minor_units)
                result["layer_consumptions"].append(value)
        return result

    def create_document(
        self,
        *,
        valuation_number: str,
        movement_id: str,
        policy_code: str,
        input_costs: Sequence[Mapping[str, object]] = (),
        valuation_date: str = "",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        number = document_number(valuation_number, "Valuation number")
        with self._transaction():
            movement = self._movement(movement_id)
            if movement["status"] != "Posted":
                raise PlatformError("Only Posted inventory movements can be prepared for valuation.")
            if movement["movement_type"] == "Transfer":
                raise PlatformError(
                    "Transfers do not create valuation documents because entity cost ownership is unchanged."
                )
            if movement["period_status"] != "Open":
                raise PlatformError("Inventory valuations can be prepared only while the movement period is Open.")
            if valuation_date:
                selected = iso_date(valuation_date, "Valuation date")
                if selected is None or selected != movement["movement_date"]:
                    raise PlatformError("Valuation date must equal the immutable inventory movement date.")
            policy_row = self.connection.execute(
                "SELECT id FROM reconforge.inventory_valuation_policies WHERE tenant_id=%s AND workspace_id=%s AND organization_id=%s AND legal_entity_id=%s AND policy_code=%s",
                (
                    self.tenant_id,
                    movement["workspace_id"],
                    movement["organization_id"],
                    movement["legal_entity_id"],
                    code(policy_code, "Valuation policy code"),
                ),
            ).fetchone()
            if policy_row is None:
                raise PlatformError("Entity-scoped valuation policy not found.")
            policy = self._policy(str(policy_row["id"]))
            if (
                not policy["active"]
                or not policy["journal_active"]
                or policy["currency_code"] != movement["entity_currency"]
                or policy["journal_currency_code"] != policy["currency_code"]
            ):
                raise PlatformError(
                    "Inventory valuation policy, journal, and movement currency must remain active and aligned."
                )
            if any(
                not policy[active] or not policy[posting]
                for active, posting in (
                    ("receipt_account_active", "receipt_account_allow_posting"),
                    ("cogs_account_active", "cogs_account_allow_posting"),
                    ("adjustment_account_active", "adjustment_account_allow_posting"),
                )
            ):
                raise PlatformError("Valuation offset accounts must remain active and posting-enabled.")
            dimensions = self.connection.execute(
                "SELECT COUNT(*) total FROM reconforge.finance_dimensions WHERE tenant_id=%s AND workspace_id=%s AND required_on_entries=TRUE AND (organization_code='' OR organization_code=%s)",
                (self.tenant_id, movement["workspace_id"], movement["organization_code"]),
            ).fetchone()
            if int(dimensions["total"]):
                raise PlatformError(
                    "Valuation approval cannot generate a Finance Draft while required dimensions are configured."
                )
            if (
                self.connection.execute(
                    "SELECT 1 FROM reconforge.inventory_valuation_documents WHERE tenant_id=%s AND movement_id=%s AND status<>'Cancelled' LIMIT 1",
                    (self.tenant_id, movement["id"]),
                ).fetchone()
                is not None
            ):
                raise PlatformError("This movement already has an active valuation document.")
            if self._active_reversal_movement(movement["id"]):
                raise PlatformError("A compensating reversal movement cannot also have a normal valuation document.")
            lines = self._movement_lines(str(movement["id"]))
            if not 1 <= len(lines) <= MAX_VALUATION_LINES:
                raise PlatformError(f"Valuation documents require between 1 and {MAX_VALUATION_LINES} movement lines.")
            inbound: dict[int, dict[str, Any]] = {}
            for line in lines:
                if (
                    line["item_type"] == "Service"
                    or not line["inventory_account_id"]
                    or not line["inventory_account_active"]
                    or not line["inventory_account_allow_posting"]
                    or line["inventory_account_chart_id"] != policy["chart_id"]
                ):
                    raise PlatformError(
                        f"Item {line['item_code']} requires an active posting inventory account in the valuation chart."
                    )
                is_inbound = movement["movement_type"] == "Receipt" or (
                    movement["movement_type"] == "Adjustment" and line["to_location_id"] is not None
                )
                if is_inbound:
                    inbound[int(line["line_number"])] = line
            currency = self._one(
                "SELECT minor_units FROM reconforge.currencies WHERE tenant_id=%s AND code=%s",
                (self.tenant_id, policy["currency_code"]),
                "Valuation currency is unavailable.",
            )
            prepared: dict[int, int] = {}
            for value in input_costs:
                if not isinstance(value, Mapping):
                    raise PlatformError("Each valuation input cost must be an object.")
                try:
                    line_number = int(str(value.get("line_number")))
                except (TypeError, ValueError) as exc:
                    raise PlatformError("Input cost line number must be a positive integer.") from exc
                if line_number not in inbound or line_number in prepared:
                    raise PlatformError("Input cost line numbers must be unique inbound movement line numbers.")
                total = amount_to_minor(value.get("total_cost"), int(currency["minor_units"]), "Input total cost")
                if total <= 0:
                    raise PlatformError("Input total cost must be greater than zero.")
                prepared[line_number] = total
            if set(prepared) != set(inbound):
                raise PlatformError("Every inbound movement line requires exactly one input total cost.")
            document_id = platform_id("IVD", movement["workspace_id"], number)
            self.connection.execute(
                """INSERT INTO reconforge.inventory_valuation_documents(tenant_id,id,workspace_id,organization_id,legal_entity_id,period_id,movement_id,policy_id,valuation_number,valuation_date,currency_code,status,created_by) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'Draft',%s)""",
                (
                    self.tenant_id,
                    document_id,
                    movement["workspace_id"],
                    movement["organization_id"],
                    movement["legal_entity_id"],
                    movement["period_id"],
                    movement["id"],
                    policy["id"],
                    number,
                    movement["movement_date"],
                    policy["currency_code"],
                    clean_text(actor_label, "Actor label"),
                ),
            )
            for line_number, total in sorted(prepared.items()):
                line = inbound[line_number]
                self.connection.execute(
                    "INSERT INTO reconforge.inventory_valuation_input_costs(tenant_id,id,valuation_document_id,movement_line_id,total_cost_minor) VALUES(%s,%s,%s,%s,%s)",
                    (self.tenant_id, platform_id("IVC", document_id, line["id"]), document_id, line["id"], total),
                )
            self._event(
                actor_label=actor_label,
                object_type="inventory_valuation_document",
                object_id=document_id,
                action="inventory_valuation_draft_created",
                version="created",
                metadata={"valuation_number": number, "movement_id": movement["id"], "input_cost_lines": len(prepared)},
            )
            return self._public_document(self._document(document_id), details=True)

    def cancel_document(self, document_id: str, *, reason: str, actor_label: str = "local-cli") -> dict[str, Any]:
        actor = clean_text(actor_label, "Actor label")
        cancel_reason = clean_text(reason, "Cancellation reason", maximum=500)
        with self._transaction():
            row = self.connection.execute(
                "UPDATE reconforge.inventory_valuation_documents SET status='Cancelled',cancelled_by=%s,cancelled_at=now(),cancel_reason=%s,updated_at=now(),row_version=row_version+1 WHERE tenant_id=%s AND id=%s AND status='Draft' RETURNING row_version",
                (actor, cancel_reason, self.tenant_id, clean_text(document_id, "Valuation document ID")),
            ).fetchone()
            if row is None:
                raise PlatformError("Only Draft inventory valuations can be cancelled.")
            self._event(
                actor_label=actor,
                object_type="inventory_valuation_document",
                object_id=document_id,
                action="inventory_valuation_cancelled",
                version=row["row_version"],
                metadata={"reason": cancel_reason},
            )
            return self._public_document(self._document(document_id), details=True)

    def get_document(self, document_id: str, *, actor_label: str = "local-cli") -> dict[str, Any]:
        with self._transaction():
            return self._public_document(self._document(document_id), details=True)

    def list_documents(
        self,
        *,
        workspace: str = "default",
        status: str = "",
        limit: int = 500,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]:
        selected = choice(status, "Valuation status", VALUATION_STATUSES) if status else ""
        limit, offset = page(limit, offset)
        with self._transaction():
            workspace_id = self._workspace_id(workspace)
            rows = self.connection.execute(
                "SELECT id FROM reconforge.inventory_valuation_documents WHERE tenant_id=%s AND workspace_id=%s AND (%s='' OR status=%s) ORDER BY valuation_date DESC,valuation_number,id LIMIT %s OFFSET %s",
                (self.tenant_id, workspace_id, selected, selected, limit, offset),
            ).fetchall()
            return [self._public_document(self._document(str(row["id"])), details=False) for row in rows]

    @staticmethod
    def _flow(movement_type: str, line: Mapping[str, object]) -> str:
        if movement_type == "Receipt":
            return "Inbound"
        if movement_type == "Delivery":
            return "Outbound"
        if movement_type == "Adjustment":
            return "Inbound" if line["to_location_id"] is not None else "Outbound"
        raise PlatformError("Transfers do not require valuation documents.")

    @staticmethod
    def _allocated_value(remaining_value: int, remaining_quantity: int, consumed_quantity: int) -> int:
        if consumed_quantity == remaining_quantity:
            return remaining_value
        exact = Decimal(remaining_value) * Decimal(consumed_quantity) / Decimal(remaining_quantity)
        value = int(exact.to_integral_value(rounding=ROUND_HALF_EVEN))
        if value <= 0 or value >= remaining_value:
            raise PlatformError("A partial FIFO issue cannot be represented exactly enough in currency minor units.")
        return value

    def _finance_draft(
        self,
        document: Mapping[str, Any],
        policy: Mapping[str, Any],
        movement: Mapping[str, Any],
        postings: Sequence[tuple[str, int, int]],
    ) -> str:
        grouped: dict[tuple[str, str], int] = {}
        for account, debit, credit in postings:
            if debit:
                grouped[(account, "debit")] = grouped.get((account, "debit"), 0) + debit
            if credit:
                grouped[(account, "credit")] = grouped.get((account, "credit"), 0) + credit
        total_debit = sum(value for (_account, side), value in grouped.items() if side == "debit")
        total_credit = sum(value for (_account, side), value in grouped.items() if side == "credit")
        if total_debit <= 0 or total_debit != total_credit:
            raise PlatformError("Generated Inventory-to-Finance postings must balance to a positive amount.")
        entry_number = f"IV-{document['valuation_number']}"
        if len(entry_number) > 64:
            entry_number = f"IV-{sha256(str(document['id']).encode()).hexdigest()[:16].upper()}"
        if (
            self.connection.execute(
                "SELECT 1 FROM reconforge.finance_entries WHERE tenant_id=%s AND workspace_id=%s AND entry_number=%s",
                (self.tenant_id, document["workspace_id"], entry_number),
            ).fetchone()
            is not None
        ):
            raise PlatformError("Generated Finance Core entry number already exists.")
        entry_id = platform_id("GLE", document["workspace_id"], entry_number)
        now = utc_now_text()
        self.connection.execute(
            """INSERT INTO reconforge.finance_entries(tenant_id,id,workspace_id,journal_id,organization_code,entity_code,period_id,entry_number,posting_date,description,external_reference,source_type,status,currency_code,total_debit_minor,total_credit_minor,created_by,created_at,updated_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'InventoryValuation','Draft',%s,%s,%s,%s,%s,%s)""",
            (
                self.tenant_id,
                entry_id,
                document["workspace_id"],
                policy["finance_journal_id"],
                movement["organization_code"],
                movement["entity_code"],
                document["period_id"],
                entry_number,
                str(movement["movement_date"]),
                f"FIFO inventory valuation {document['valuation_number']}",
                f"Inventory movement {movement['movement_number']}",
                document["currency_code"],
                total_debit,
                total_credit,
                document["created_by"],
                now,
                now,
            ),
        )
        ordered = sorted(grouped.items(), key=lambda item: (item[0][1] != "debit", item[0][0]))
        for number, ((account, side), value) in enumerate(ordered, 1):
            self.connection.execute(
                "INSERT INTO reconforge.finance_entry_lines(tenant_id,id,entry_id,line_number,account_id,description,debit_minor,credit_minor,currency_code) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    self.tenant_id,
                    platform_id("GLL", entry_id, number),
                    entry_id,
                    number,
                    account,
                    f"FIFO valuation {document['valuation_number']}",
                    value if side == "debit" else 0,
                    value if side == "credit" else 0,
                    document["currency_code"],
                ),
            )
        return entry_id

    def approve_document(self, document_id: str, *, reason: str, actor_label: str = "local-cli") -> dict[str, Any]:
        actor = clean_text(actor_label, "Actor label")
        approval_reason = clean_text(reason, "Approval reason", maximum=500)
        with self._transaction():
            locked = self.connection.execute(
                "SELECT id FROM reconforge.inventory_valuation_documents WHERE tenant_id=%s AND id=%s FOR UPDATE",
                (self.tenant_id, clean_text(document_id, "Valuation document ID")),
            ).fetchone()
            if locked is None:
                raise PlatformError("Inventory valuation document not found.")
            document = self._document(document_id)
            if document["status"] != "Draft":
                raise PlatformError("Only Draft inventory valuations can be approved.")
            if same_actor(document["created_by"], actor):
                raise PlatformError("Segregation of duties prevents approving your own inventory valuation.")
            movement = self._movement(str(document["movement_id"]))
            policy = self._policy(str(document["policy_id"]))
            if movement["status"] != "Posted" or movement["period_status"] != "Open":
                raise PlatformError("Valuation approval requires a Posted movement in an Open period.")
            if (
                not policy["active"]
                or not policy["journal_active"]
                or policy["currency_code"] != movement["entity_currency"]
                or policy["journal_currency_code"] != policy["currency_code"]
            ):
                raise PlatformError(
                    "Inventory valuation policy, journal, and movement currency must remain active and aligned."
                )
            if any(
                not policy[active] or not policy[posting]
                for active, posting in (
                    ("receipt_account_active", "receipt_account_allow_posting"),
                    ("cogs_account_active", "cogs_account_allow_posting"),
                    ("adjustment_account_active", "adjustment_account_allow_posting"),
                )
            ):
                raise PlatformError("Valuation offset accounts must remain active and posting-enabled.")
            dimensions = self.connection.execute(
                "SELECT COUNT(*) total FROM reconforge.finance_dimensions WHERE tenant_id=%s AND workspace_id=%s AND required_on_entries=TRUE AND (organization_code='' OR organization_code=%s)",
                (self.tenant_id, document["workspace_id"], movement["organization_code"]),
            ).fetchone()
            if int(dimensions["total"]):
                raise PlatformError(
                    "Valuation approval cannot generate a Finance Draft while required dimensions are configured."
                )
            earlier_sql = (
                """SELECT e.movement_number FROM reconforge.inventory_movements c JOIN reconforge.inventory_movements e ON e.tenant_id=c.tenant_id AND e.workspace_id=c.workspace_id AND e.organization_id=c.organization_id AND e.legal_entity_id=c.legal_entity_id AND e.status='Posted' AND e.movement_type<>'Transfer' AND (e.movement_date<c.movement_date OR (e.movement_date=c.movement_date AND e.movement_number<c.movement_number)) WHERE c.tenant_id=%s AND c.id=%s AND NOT EXISTS(SELECT 1 FROM reconforge.inventory_valuation_documents d WHERE d.tenant_id=e.tenant_id AND d.movement_id=e.id AND d.status='Approved') AND NOT EXISTS(SELECT 1 FROM reconforge.inventory_valuation_reversals r WHERE r.tenant_id=e.tenant_id AND r.reversal_movement_id=e.id AND r.status='Approved') ORDER BY e.movement_date,e.movement_number LIMIT 1"""
                if self._reversal_schema_available()
                else """SELECT e.movement_number FROM reconforge.inventory_movements c JOIN reconforge.inventory_movements e ON e.tenant_id=c.tenant_id AND e.workspace_id=c.workspace_id AND e.organization_id=c.organization_id AND e.legal_entity_id=c.legal_entity_id AND e.status='Posted' AND e.movement_type<>'Transfer' AND (e.movement_date<c.movement_date OR (e.movement_date=c.movement_date AND e.movement_number<c.movement_number)) WHERE c.tenant_id=%s AND c.id=%s AND NOT EXISTS(SELECT 1 FROM reconforge.inventory_valuation_documents d WHERE d.tenant_id=e.tenant_id AND d.movement_id=e.id AND d.status='Approved') ORDER BY e.movement_date,e.movement_number LIMIT 1"""
            )
            earlier = self.connection.execute(earlier_sql, (self.tenant_id, movement["id"])).fetchone()
            if earlier is not None:
                raise PlatformError(
                    f"FIFO approval requires earlier Posted movement {earlier['movement_number']} to be valued first."
                )
            later = self.connection.execute(
                """SELECT d.valuation_number FROM reconforge.inventory_movements c JOIN reconforge.inventory_movements l ON l.tenant_id=c.tenant_id AND l.workspace_id=c.workspace_id AND l.organization_id=c.organization_id AND l.legal_entity_id=c.legal_entity_id AND (l.movement_date>c.movement_date OR (l.movement_date=c.movement_date AND l.movement_number>c.movement_number)) JOIN reconforge.inventory_valuation_documents d ON d.tenant_id=l.tenant_id AND d.movement_id=l.id AND d.status='Approved' WHERE c.tenant_id=%s AND c.id=%s ORDER BY l.movement_date,l.movement_number LIMIT 1""",
                (self.tenant_id, movement["id"]),
            ).fetchone()
            if later is not None:
                raise PlatformError(
                    f"Backdated FIFO approval is blocked because later valuation {later['valuation_number']} is already Approved."
                )
            input_rows = self.connection.execute(
                "SELECT movement_line_id,total_cost_minor FROM reconforge.inventory_valuation_input_costs WHERE tenant_id=%s AND valuation_document_id=%s",
                (self.tenant_id, document_id),
            ).fetchall()
            input_costs = {str(row["movement_line_id"]): int(row["total_cost_minor"]) for row in input_rows}
            postings: list[tuple[str, int, int]] = []
            total = 0
            for line in self._movement_lines(str(movement["id"])):
                if (
                    line["item_type"] == "Service"
                    or not line["inventory_account_id"]
                    or not line["inventory_account_active"]
                    or not line["inventory_account_allow_posting"]
                    or line["inventory_account_chart_id"] != policy["chart_id"]
                ):
                    raise PlatformError(
                        f"Item {line['item_code']} requires an active posting inventory account in the valuation chart."
                    )
                flow = self._flow(str(movement["movement_type"]), line)
                value = 0
                allocations = []
                if flow == "Inbound":
                    value = input_costs.get(str(line["id"]), 0)
                else:
                    lock_key = f"{document['legal_entity_id']}|{line['item_id']}|{line['inventory_lot_id'] or ''}"
                    self.connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (lock_key,))
                    needed = int(line["quantity_scaled"])
                    layers = self.connection.execute(
                        """SELECT * FROM reconforge.inventory_cost_layers WHERE tenant_id=%s AND legal_entity_id=%s AND item_id=%s AND inventory_lot_id IS NOT DISTINCT FROM %s AND remaining_quantity_scaled>0 ORDER BY created_at,id FOR UPDATE""",
                        (self.tenant_id, document["legal_entity_id"], line["item_id"], line["inventory_lot_id"]),
                    ).fetchall()
                    for layer_row in layers:
                        if needed <= 0:
                            break
                        layer = dict(layer_row)
                        if (
                            int(layer["quantity_precision"]) != int(line["quantity_precision"])
                            or layer["uom_id"] != line["uom_id"]
                        ):
                            raise PlatformError("FIFO layer unit precision does not match the outbound movement line.")
                        take = min(needed, int(layer["remaining_quantity_scaled"]))
                        allocated = self._allocated_value(
                            int(layer["remaining_value_minor"]), int(layer["remaining_quantity_scaled"]), take
                        )
                        allocations.append((layer, take, allocated))
                        value += allocated
                        needed -= take
                    if needed:
                        raise PlatformError(
                            f"Insufficient Approved FIFO quantity for outbound line {line['line_number']}."
                        )
                if value <= 0:
                    raise PlatformError("Every valuation line must carry a positive currency value.")
                total += value
                if total > MAX_AMOUNT_MINOR:
                    raise PlatformError("Valuation total exceeds the supported amount range.")
                valuation_line_id = platform_id("IVL", document_id, line["id"])
                offset = (
                    policy["receipt_clearing_account_id"]
                    if movement["movement_type"] == "Receipt"
                    else policy["cogs_account_id"]
                    if movement["movement_type"] == "Delivery"
                    else policy["adjustment_account_id"]
                )
                self.connection.execute(
                    """INSERT INTO reconforge.inventory_valuation_lines(tenant_id,id,valuation_document_id,movement_line_id,line_number,flow_direction,item_id,uom_id,inventory_lot_id,quantity_scaled,quantity_precision,value_minor,inventory_account_id,offset_account_id) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        self.tenant_id,
                        valuation_line_id,
                        document_id,
                        line["id"],
                        line["line_number"],
                        flow,
                        line["item_id"],
                        line["uom_id"],
                        line["inventory_lot_id"],
                        line["quantity_scaled"],
                        line["quantity_precision"],
                        value,
                        line["inventory_account_id"],
                        offset,
                    ),
                )
                if flow == "Inbound":
                    self.connection.execute(
                        """INSERT INTO reconforge.inventory_cost_layers(tenant_id,id,workspace_id,source_valuation_line_id,legal_entity_id,item_id,uom_id,inventory_lot_id,quantity_precision,original_quantity_scaled,remaining_quantity_scaled,original_value_minor,remaining_value_minor,currency_code) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (
                            self.tenant_id,
                            platform_id("IVR", valuation_line_id),
                            document["workspace_id"],
                            valuation_line_id,
                            document["legal_entity_id"],
                            line["item_id"],
                            line["uom_id"],
                            line["inventory_lot_id"],
                            line["quantity_precision"],
                            line["quantity_scaled"],
                            line["quantity_scaled"],
                            value,
                            value,
                            document["currency_code"],
                        ),
                    )
                else:
                    for layer, take, allocated in allocations:
                        self.connection.execute(
                            "INSERT INTO reconforge.inventory_layer_consumptions(tenant_id,id,workspace_id,valuation_line_id,cost_layer_id,quantity_scaled,value_minor) VALUES(%s,%s,%s,%s,%s,%s,%s)",
                            (
                                self.tenant_id,
                                platform_id("IVX", valuation_line_id, layer["id"]),
                                document["workspace_id"],
                                valuation_line_id,
                                layer["id"],
                                take,
                                allocated,
                            ),
                        )
                        self.connection.execute(
                            "UPDATE reconforge.inventory_cost_layers SET remaining_quantity_scaled=remaining_quantity_scaled-%s,remaining_value_minor=remaining_value_minor-%s,row_version=row_version+1 WHERE tenant_id=%s AND id=%s",
                            (take, allocated, self.tenant_id, layer["id"]),
                        )
                postings.extend(
                    ((str(line["inventory_account_id"]), value, 0), (str(offset), 0, value))
                    if flow == "Inbound"
                    else ((str(offset), value, 0), (str(line["inventory_account_id"]), 0, value))
                )
            finance_entry_id = self._finance_draft(document, policy, movement, postings)
            row = self.connection.execute(
                "UPDATE reconforge.inventory_valuation_documents SET status='Approved',total_value_minor=%s,finance_entry_id=%s,approved_by=%s,approved_at=now(),approval_reason=%s,updated_at=now(),row_version=row_version+1 WHERE tenant_id=%s AND id=%s AND status='Draft' RETURNING row_version",
                (total, finance_entry_id, actor, approval_reason, self.tenant_id, document_id),
            ).fetchone()
            if row is None:
                raise PlatformError("Inventory valuation changed concurrently; reload and retry.")
            self._event(
                actor_label=actor,
                object_type="inventory_valuation_document",
                object_id=document_id,
                action="inventory_valuation_approved",
                version=row["row_version"],
                metadata={
                    "valuation_number": document["valuation_number"],
                    "total_value_minor": total,
                    "finance_entry_id": finance_entry_id,
                },
            )
            return self._public_document(self._document(document_id), details=True)

    def list_cost_layers(
        self,
        *,
        workspace: str = "default",
        open_only: bool = False,
        limit: int = 500,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]:
        limit, offset = page(limit, offset)
        with self._transaction():
            workspace_id = self._workspace_id(workspace)
            rows = self.connection.execute(
                """SELECT l.*,i.item_code,u.uom_code,lot.lot_serial_code,e.entity_code,d.valuation_number,c.minor_units FROM reconforge.inventory_cost_layers l JOIN reconforge.inventory_items i ON i.tenant_id=l.tenant_id AND i.id=l.item_id JOIN reconforge.inventory_units_of_measure u ON u.tenant_id=l.tenant_id AND u.id=l.uom_id LEFT JOIN reconforge.inventory_lots lot ON lot.tenant_id=l.tenant_id AND lot.id=l.inventory_lot_id JOIN reconforge.legal_entities e ON e.tenant_id=l.tenant_id AND e.id=l.legal_entity_id JOIN reconforge.inventory_valuation_lines v ON v.tenant_id=l.tenant_id AND v.id=l.source_valuation_line_id JOIN reconforge.inventory_valuation_documents d ON d.tenant_id=l.tenant_id AND d.id=v.valuation_document_id JOIN reconforge.currencies c ON c.tenant_id=l.tenant_id AND c.code=l.currency_code WHERE l.tenant_id=%s AND l.workspace_id=%s AND d.status='Approved' AND (%s=FALSE OR l.remaining_quantity_scaled>0) ORDER BY l.created_at,l.id LIMIT %s OFFSET %s""",
                (self.tenant_id, workspace_id, open_only, limit, offset),
            ).fetchall()
            result = []
            for row in rows:
                value = public_record(row)
                precision = int(value["quantity_precision"])
                minor = int(value.pop("minor_units"))
                value["original_quantity"] = scaled_to_text(int(value.pop("original_quantity_scaled")), precision)
                value["remaining_quantity"] = scaled_to_text(int(value.pop("remaining_quantity_scaled")), precision)
                value["original_value"] = minor_to_text(int(value.pop("original_value_minor")), minor)
                value["remaining_value"] = minor_to_text(int(value.pop("remaining_value_minor")), minor)
                value["layer_status"] = (
                    "Open" if value["remaining_quantity"] != scaled_to_text(0, precision) else "Closed"
                )
                result.append(value)
            return result

    def summary(self, *, workspace: str = "default", actor_label: str = "local-cli") -> InventoryValuationSummary:
        workspace_name = clean_text(workspace, "Workspace name")
        with self._transaction():
            workspace_id = self._workspace_id(workspace_name)
            if self._reversal_schema_available():
                row = self.connection.execute(
                    """SELECT
                  (SELECT COUNT(*) FROM reconforge.inventory_valuation_policies WHERE tenant_id=%s AND workspace_id=%s) policies,
                  (SELECT COUNT(*) FROM reconforge.inventory_valuation_documents WHERE tenant_id=%s AND workspace_id=%s AND status='Draft') drafts,
                  (SELECT COUNT(*) FROM reconforge.inventory_valuation_documents WHERE tenant_id=%s AND workspace_id=%s AND status='Approved') approved,
                  (SELECT COUNT(*) FROM reconforge.inventory_cost_layers WHERE tenant_id=%s AND workspace_id=%s AND remaining_quantity_scaled>0) layers,
                  (SELECT COUNT(*) FROM reconforge.inventory_movements m WHERE m.tenant_id=%s AND m.workspace_id=%s AND m.status='Posted' AND m.movement_type<>'Transfer' AND NOT EXISTS(SELECT 1 FROM reconforge.inventory_valuation_documents d WHERE d.tenant_id=m.tenant_id AND d.movement_id=m.id AND d.status='Approved') AND NOT EXISTS(SELECT 1 FROM reconforge.inventory_valuation_reversals r WHERE r.tenant_id=m.tenant_id AND r.reversal_movement_id=m.id AND r.status='Approved')) unvalued""",
                    (self.tenant_id, workspace_id) * 5,
                ).fetchone()
            else:
                row = self.connection.execute(
                    """SELECT
                  (SELECT COUNT(*) FROM reconforge.inventory_valuation_policies WHERE tenant_id=%s AND workspace_id=%s) policies,
                  (SELECT COUNT(*) FROM reconforge.inventory_valuation_documents WHERE tenant_id=%s AND workspace_id=%s AND status='Draft') drafts,
                  (SELECT COUNT(*) FROM reconforge.inventory_valuation_documents WHERE tenant_id=%s AND workspace_id=%s AND status='Approved') approved,
                  (SELECT COUNT(*) FROM reconforge.inventory_cost_layers WHERE tenant_id=%s AND workspace_id=%s AND remaining_quantity_scaled>0) layers,
                  (SELECT COUNT(*) FROM reconforge.inventory_movements m WHERE m.tenant_id=%s AND m.workspace_id=%s AND m.status='Posted' AND m.movement_type<>'Transfer' AND NOT EXISTS(SELECT 1 FROM reconforge.inventory_valuation_documents d WHERE d.tenant_id=m.tenant_id AND d.movement_id=m.id AND d.status='Approved')) unvalued""",
                    (self.tenant_id, workspace_id) * 5,
                ).fetchone()
            return InventoryValuationSummary(
                workspace_name,
                int(row["policies"]),
                int(row["drafts"]),
                int(row["approved"]),
                int(row["layers"]),
                int(row["unvalued"]),
            )

    def snapshot(self, *, workspace: str = "default", actor_label: str = "local-cli") -> dict[str, Any]:
        workspace_name = clean_text(workspace, "Workspace name")
        return {
            "schema_version": 1,
            "generated_at": utc_now_text(),
            "source": {"kind": "local-inventory-valuation", "local_first": True, "external_calls": False},
            "workspace": workspace_name,
            "summary": self.summary(workspace=workspace_name, actor_label=actor_label).to_dict(),
            "policies": self.list_policies(workspace=workspace_name, actor_label=actor_label),
            "documents": self.list_documents(workspace=workspace_name, actor_label=actor_label),
            "open_cost_layers": self.list_cost_layers(
                workspace=workspace_name, open_only=True, actor_label=actor_label
            ),
            "boundary_note": "FIFO foundation only. Approval creates a balanced local Finance Core Draft; it does not validate that entry or write to a source ERP.",
        }
