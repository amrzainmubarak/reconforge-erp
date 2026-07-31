"""PostgreSQL adapter for governed Inventory Core."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from typing import Any

from reconforge.application.inventory_core import InventoryCoreSummary
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
    iso_date,
    page,
    public_record,
    quantity_to_scaled,
    scaled_to_text,
)
from reconforge.platform.inventory_values import (
    movement_number as normalize_movement_number,
)
from reconforge.utils.time import utc_now_text, utc_today

MOVEMENT_TYPES = ("Receipt", "Delivery", "Transfer", "Adjustment")
MOVEMENT_SOURCE_TYPES = ("Manual", "Imported", "Generated")
MAX_MOVEMENT_LINES = 1_000

UOM_CATEGORIES = ("Count", "Weight", "Volume", "Length", "Time", "Custom")
ITEM_TYPES = ("Stock", "Consumable", "Service")
TRACKING_MODES = ("None", "Lot", "Serial")
LOCATION_TYPES = ("Internal", "Transit", "Supplier", "Customer", "Adjustment")


class PostgresInventoryCoreError(RuntimeError):
    """Safe PostgreSQL Inventory Core failure."""


POSTGRES_INVENTORY_CORE_SCHEMA_SQL = r"""
CREATE TABLE IF NOT EXISTS reconforge.inventory_units_of_measure (
    tenant_id TEXT NOT NULL, id TEXT NOT NULL, workspace_id TEXT NOT NULL,
    uom_code TEXT NOT NULL, name TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'Count' CHECK (category IN ('Count','Weight','Volume','Length','Time','Custom')),
    decimal_places INTEGER NOT NULL DEFAULT 0 CHECK (decimal_places BETWEEN 0 AND 6),
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    row_version BIGINT NOT NULL DEFAULT 1 CHECK (row_version > 0),
    PRIMARY KEY (tenant_id,id), UNIQUE (tenant_id,workspace_id,uom_code),
    FOREIGN KEY (tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS reconforge.inventory_items (
    tenant_id TEXT NOT NULL, id TEXT NOT NULL, workspace_id TEXT NOT NULL,
    organization_id TEXT, item_code TEXT NOT NULL, name TEXT NOT NULL,
    item_type TEXT NOT NULL DEFAULT 'Stock' CHECK (item_type IN ('Stock','Consumable','Service')),
    tracking_mode TEXT NOT NULL DEFAULT 'None' CHECK (tracking_mode IN ('None','Lot','Serial')),
    uom_id TEXT NOT NULL, inventory_account_id TEXT, description TEXT NOT NULL DEFAULT '',
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    row_version BIGINT NOT NULL DEFAULT 1 CHECK (row_version > 0),
    PRIMARY KEY (tenant_id,id), UNIQUE (tenant_id,workspace_id,item_code),
    FOREIGN KEY (tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id,organization_id) REFERENCES reconforge.organizations(tenant_id,id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id,uom_id) REFERENCES reconforge.inventory_units_of_measure(tenant_id,id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id,inventory_account_id) REFERENCES reconforge.finance_accounts(tenant_id,id) ON DELETE RESTRICT,
    CHECK (item_type <> 'Service' OR tracking_mode = 'None')
);
CREATE TABLE IF NOT EXISTS reconforge.inventory_warehouses (
    tenant_id TEXT NOT NULL, id TEXT NOT NULL, workspace_id TEXT NOT NULL,
    organization_id TEXT NOT NULL, legal_entity_id TEXT, warehouse_code TEXT NOT NULL,
    name TEXT NOT NULL, active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    row_version BIGINT NOT NULL DEFAULT 1 CHECK (row_version > 0),
    PRIMARY KEY (tenant_id,id), UNIQUE (tenant_id,workspace_id,organization_id,warehouse_code),
    FOREIGN KEY (tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id,organization_id) REFERENCES reconforge.organizations(tenant_id,id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id,legal_entity_id) REFERENCES reconforge.legal_entities(tenant_id,id) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS reconforge.inventory_locations (
    tenant_id TEXT NOT NULL, id TEXT NOT NULL, warehouse_id TEXT NOT NULL,
    parent_location_id TEXT, location_code TEXT NOT NULL, name TEXT NOT NULL,
    location_type TEXT NOT NULL DEFAULT 'Internal' CHECK (location_type IN ('Internal','Transit','Supplier','Customer','Adjustment')),
    allow_negative BOOLEAN NOT NULL DEFAULT FALSE, active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    row_version BIGINT NOT NULL DEFAULT 1 CHECK (row_version > 0),
    PRIMARY KEY (tenant_id,id), UNIQUE (tenant_id,warehouse_id,location_code),
    FOREIGN KEY (tenant_id,warehouse_id) REFERENCES reconforge.inventory_warehouses(tenant_id,id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id,parent_location_id) REFERENCES reconforge.inventory_locations(tenant_id,id) ON DELETE RESTRICT,
    CHECK (parent_location_id IS NULL OR parent_location_id <> id)
);
CREATE TABLE IF NOT EXISTS reconforge.inventory_lots (
    tenant_id TEXT NOT NULL, id TEXT NOT NULL, workspace_id TEXT NOT NULL,
    organization_id TEXT NOT NULL, item_id TEXT NOT NULL, lot_serial_code TEXT NOT NULL,
    tracking_type TEXT NOT NULL CHECK (tracking_type IN ('Lot','Serial')),
    manufactured_on DATE, expires_on DATE, active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    row_version BIGINT NOT NULL DEFAULT 1 CHECK (row_version > 0),
    PRIMARY KEY (tenant_id,id), UNIQUE (tenant_id,item_id,organization_id,lot_serial_code),
    FOREIGN KEY (tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id,organization_id) REFERENCES reconforge.organizations(tenant_id,id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id,item_id) REFERENCES reconforge.inventory_items(tenant_id,id) ON DELETE RESTRICT,
    CHECK (manufactured_on IS NULL OR expires_on IS NULL OR manufactured_on <= expires_on)
);
CREATE TABLE IF NOT EXISTS reconforge.inventory_movements (
    tenant_id TEXT NOT NULL, id TEXT NOT NULL, workspace_id TEXT NOT NULL,
    organization_id TEXT NOT NULL, legal_entity_id TEXT NOT NULL, period_id TEXT NOT NULL,
    movement_number TEXT NOT NULL, movement_type TEXT NOT NULL CHECK (movement_type IN ('Receipt','Delivery','Transfer','Adjustment')),
    movement_date DATE NOT NULL, source_reference TEXT NOT NULL DEFAULT '', description TEXT NOT NULL,
    source_type TEXT NOT NULL DEFAULT 'Manual' CHECK (source_type IN ('Manual','Imported','Generated')),
    status TEXT NOT NULL DEFAULT 'Draft' CHECK (status IN ('Draft','Posted','Voided')),
    created_by TEXT NOT NULL, posted_by TEXT NOT NULL DEFAULT '', posted_at TIMESTAMPTZ,
    post_reason TEXT NOT NULL DEFAULT '', voided_by TEXT NOT NULL DEFAULT '', voided_at TIMESTAMPTZ,
    void_reason TEXT NOT NULL DEFAULT '', created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), row_version BIGINT NOT NULL DEFAULT 1 CHECK (row_version > 0),
    PRIMARY KEY (tenant_id,id), UNIQUE (tenant_id,workspace_id,movement_number),
    FOREIGN KEY (tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id,organization_id) REFERENCES reconforge.organizations(tenant_id,id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id,legal_entity_id) REFERENCES reconforge.legal_entities(tenant_id,id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id,period_id) REFERENCES reconforge.fiscal_periods(tenant_id,id) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS reconforge.inventory_movement_lines (
    tenant_id TEXT NOT NULL, id TEXT NOT NULL, movement_id TEXT NOT NULL,
    line_number INTEGER NOT NULL CHECK (line_number > 0), item_id TEXT NOT NULL,
    uom_id TEXT NOT NULL, inventory_lot_id TEXT, from_location_id TEXT, to_location_id TEXT,
    quantity_scaled BIGINT NOT NULL CHECK (quantity_scaled > 0),
    quantity_precision INTEGER NOT NULL CHECK (quantity_precision BETWEEN 0 AND 6),
    description TEXT NOT NULL DEFAULT '', created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id,id), UNIQUE (tenant_id,movement_id,line_number),
    FOREIGN KEY (tenant_id,movement_id) REFERENCES reconforge.inventory_movements(tenant_id,id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id,item_id) REFERENCES reconforge.inventory_items(tenant_id,id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id,uom_id) REFERENCES reconforge.inventory_units_of_measure(tenant_id,id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id,inventory_lot_id) REFERENCES reconforge.inventory_lots(tenant_id,id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id,from_location_id) REFERENCES reconforge.inventory_locations(tenant_id,id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id,to_location_id) REFERENCES reconforge.inventory_locations(tenant_id,id) ON DELETE RESTRICT,
    CHECK (from_location_id IS NOT NULL OR to_location_id IS NOT NULL),
    CHECK (from_location_id IS NULL OR to_location_id IS NULL OR from_location_id <> to_location_id)
);
CREATE INDEX IF NOT EXISTS inventory_items_scope_idx ON reconforge.inventory_items(tenant_id,workspace_id,organization_id,active,item_code);
CREATE INDEX IF NOT EXISTS inventory_warehouses_scope_idx ON reconforge.inventory_warehouses(tenant_id,workspace_id,organization_id,legal_entity_id,active,warehouse_code);
CREATE INDEX IF NOT EXISTS inventory_locations_scope_idx ON reconforge.inventory_locations(tenant_id,warehouse_id,parent_location_id,active,location_code);
CREATE INDEX IF NOT EXISTS inventory_lots_scope_idx ON reconforge.inventory_lots(tenant_id,item_id,active,lot_serial_code);
CREATE INDEX IF NOT EXISTS inventory_movements_scope_idx ON reconforge.inventory_movements(tenant_id,workspace_id,organization_id,legal_entity_id,period_id,status,movement_date,id);
CREATE INDEX IF NOT EXISTS inventory_lines_stock_idx ON reconforge.inventory_movement_lines(tenant_id,item_id,inventory_lot_id,from_location_id,to_location_id,movement_id);

CREATE OR REPLACE FUNCTION reconforge.inventory_guard_movement_line() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE movement_status TEXT; target_tenant TEXT; target_movement TEXT;
BEGIN
  IF TG_OP='DELETE' THEN
    target_tenant:=OLD.tenant_id; target_movement:=OLD.movement_id;
  ELSE
    target_tenant:=NEW.tenant_id; target_movement:=NEW.movement_id;
  END IF;
  SELECT status INTO movement_status FROM reconforge.inventory_movements
   WHERE tenant_id=target_tenant AND id=target_movement;
  IF movement_status IS DISTINCT FROM 'Draft' THEN
    RAISE EXCEPTION 'posted inventory movement lines are immutable';
  END IF;
  IF TG_OP='DELETE' THEN RETURN OLD; END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS inventory_movement_lines_draft_only ON reconforge.inventory_movement_lines;
CREATE TRIGGER inventory_movement_lines_draft_only BEFORE INSERT OR UPDATE OR DELETE
ON reconforge.inventory_movement_lines FOR EACH ROW EXECUTE FUNCTION reconforge.inventory_guard_movement_line();

CREATE OR REPLACE FUNCTION reconforge.inventory_guard_movement_header() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.status <> OLD.status AND NOT ((OLD.status='Draft' AND NEW.status='Posted') OR (OLD.status='Posted' AND NEW.status='Voided')) THEN
    RAISE EXCEPTION 'invalid inventory movement status transition';
  END IF;
  IF OLD.status <> 'Draft' AND
     (NEW.workspace_id,NEW.organization_id,NEW.legal_entity_id,NEW.period_id,NEW.movement_number,
      NEW.movement_type,NEW.movement_date,NEW.source_reference,NEW.description,NEW.source_type,NEW.created_by,NEW.created_at)
     IS DISTINCT FROM
     (OLD.workspace_id,OLD.organization_id,OLD.legal_entity_id,OLD.period_id,OLD.movement_number,
      OLD.movement_type,OLD.movement_date,OLD.source_reference,OLD.description,OLD.source_type,OLD.created_by,OLD.created_at)
  THEN RAISE EXCEPTION 'posted inventory movement headers are immutable'; END IF;
  IF OLD.status='Draft' AND NEW.status='Posted' AND
     (NEW.posted_by='' OR NEW.posted_at IS NULL OR NEW.post_reason='' OR
      NOT EXISTS (SELECT 1 FROM reconforge.inventory_movement_lines l WHERE l.tenant_id=OLD.tenant_id AND l.movement_id=OLD.id) OR
      EXISTS (SELECT 1 FROM reconforge.inventory_movement_lines l
               WHERE l.tenant_id=OLD.tenant_id AND l.movement_id=OLD.id AND (
                 (OLD.movement_type='Receipt' AND (l.from_location_id IS NOT NULL OR l.to_location_id IS NULL)) OR
                 (OLD.movement_type='Delivery' AND (l.from_location_id IS NULL OR l.to_location_id IS NOT NULL)) OR
                 (OLD.movement_type='Transfer' AND (l.from_location_id IS NULL OR l.to_location_id IS NULL)) OR
                 (OLD.movement_type='Adjustment' AND ((l.from_location_id IS NULL)=(l.to_location_id IS NULL)))
               )))
  THEN RAISE EXCEPTION 'inventory movement posting requires lines and review metadata'; END IF;
  IF OLD.status='Posted' AND NEW.status='Voided' AND
     (NEW.voided_by='' OR NEW.voided_at IS NULL OR NEW.void_reason='')
  THEN RAISE EXCEPTION 'voiding an inventory movement requires actor timestamp and reason'; END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS inventory_movement_governance ON reconforge.inventory_movements;
CREATE TRIGGER inventory_movement_governance BEFORE UPDATE ON reconforge.inventory_movements
FOR EACH ROW EXECUTE FUNCTION reconforge.inventory_guard_movement_header();

DO $rls$
DECLARE table_name TEXT;
BEGIN
  FOREACH table_name IN ARRAY ARRAY['inventory_units_of_measure','inventory_items','inventory_warehouses','inventory_locations','inventory_lots','inventory_movements','inventory_movement_lines'] LOOP
    EXECUTE format('ALTER TABLE reconforge.%I ENABLE ROW LEVEL SECURITY',table_name);
    EXECUTE format('ALTER TABLE reconforge.%I FORCE ROW LEVEL SECURITY',table_name);
    EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON reconforge.%I',table_name);
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname='reconforge' AND tablename=table_name AND policyname='tenant_scope') THEN
     EXECUTE format('CREATE POLICY tenant_isolation ON reconforge.%I USING (tenant_id=current_setting(''app.tenant_id'',true)) WITH CHECK (tenant_id=current_setting(''app.tenant_id'',true))',table_name);
    END IF;
  END LOOP;
END $rls$;
"""


def _row(value: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    record = dict(value) if isinstance(value, Mapping) else dict(zip(fields, value, strict=True))
    return public_record(record)


class PostgresInventoryCoreRepository:
    """Tenant-scoped PostgreSQL Inventory Core adapter."""

    def __init__(self, connection: Any, tenant_id: str) -> None:
        self.connection = connection
        self.tenant_id = validate_tenant_id(tenant_id)

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        try:
            with self.connection.transaction():
                set_local_tenant_scope(self.connection, self.tenant_id)
                yield
        except (PlatformError, PostgresInventoryCoreError):
            raise
        except Exception as exc:
            raise PostgresInventoryCoreError("PostgreSQL Inventory Core operation failed.") from exc

    def _one(self, sql: str, params: tuple[object, ...], message: str) -> dict[str, Any]:
        row = self.connection.execute(sql, params).fetchone()
        if row is None:
            raise PlatformError(message)
        return dict(row) if isinstance(row, Mapping) else dict(row)

    def _workspace_id(self, workspace: str) -> str:
        row = self.connection.execute(
            "SELECT id FROM reconforge.domain_workspaces WHERE tenant_id=%s AND name=%s",
            (self.tenant_id, clean_text(workspace, "Workspace name")),
        ).fetchone()
        if row is None:
            raise PlatformError("Inventory workspace was not found for this tenant.")
        return str(row["id"] if isinstance(row, Mapping) else row[0])

    def _organization(self, workspace_id: str, organization_code: str) -> dict[str, Any]:
        return self._one(
            """SELECT o.id,o.organization_code,o.active FROM reconforge.organizations o
            JOIN reconforge.master_data_workspace_organizations w ON w.tenant_id=o.tenant_id AND w.organization_id=o.id
            WHERE o.tenant_id=%s AND w.workspace_id=%s AND o.organization_code=%s AND o.active=TRUE""",
            (self.tenant_id, workspace_id, code(organization_code, "Organization code")),
            "Inventory organization was not found or inactive in this workspace.",
        )

    def _entity(self, organization_id: str, entity_code: str) -> dict[str, Any] | None:
        if not entity_code.strip():
            return None
        return self._one(
            "SELECT id,entity_code,active FROM reconforge.legal_entities WHERE tenant_id=%s AND organization_id=%s AND entity_code=%s AND active=TRUE",
            (self.tenant_id, organization_id, code(entity_code, "Entity code")),
            "Inventory legal entity was not found or inactive.",
        )

    def _event(
        self,
        *,
        actor_label: str,
        object_type: str,
        object_id: str,
        action: str,
        metadata: dict[str, Any],
        version: object,
    ) -> None:
        try:
            payload = encode_postgres_outbox_payload(metadata).text
        except PersistedJsonError as exc:
            raise PostgresInventoryCoreError("Inventory event payload is invalid.") from exc
        event_id = platform_id("OBX", action, object_id, version)
        self.connection.execute(
            """INSERT INTO reconforge.outbox_events
            (tenant_id,event_id,event_type,aggregate_type,aggregate_id,payload)
            VALUES (%s,%s,%s,%s,%s,CAST(%s AS jsonb)) ON CONFLICT (tenant_id,event_id) DO NOTHING""",
            (self.tenant_id, event_id, action, object_type, object_id, payload),
        )
        PostgresAuditEventRepository(self.connection, self.tenant_id).append(
            actor_label=clean_text(actor_label, "Actor label"),
            object_type=object_type,
            object_id=object_id,
            action=action,
            metadata=metadata,
        )

    def _uom(self, workspace_id: str, uom_code: str, *, active: bool = False) -> dict[str, Any]:
        return self._one(
            "SELECT * FROM reconforge.inventory_units_of_measure WHERE tenant_id=%s AND workspace_id=%s AND uom_code=%s AND (%s=FALSE OR active=TRUE)",
            (self.tenant_id, workspace_id, code(uom_code, "Unit code"), active),
            "Inventory unit was not found or inactive.",
        )

    def _item(self, workspace_id: str, item_code: str, *, active: bool = False) -> dict[str, Any]:
        return self._one(
            """SELECT i.*,u.uom_code,u.decimal_places,u.active uom_active
            FROM reconforge.inventory_items i JOIN reconforge.inventory_units_of_measure u
            ON u.tenant_id=i.tenant_id AND u.id=i.uom_id
            WHERE i.tenant_id=%s AND i.workspace_id=%s AND i.item_code=%s
              AND (%s=FALSE OR i.active=TRUE)""",
            (self.tenant_id, workspace_id, code(item_code, "Item code"), active),
            "Inventory item was not found or inactive.",
        )

    def _warehouse(
        self, workspace_id: str, organization_id: str, warehouse_code: str, *, active: bool = False
    ) -> dict[str, Any]:
        return self._one(
            "SELECT * FROM reconforge.inventory_warehouses WHERE tenant_id=%s AND workspace_id=%s AND organization_id=%s AND warehouse_code=%s AND (%s=FALSE OR active=TRUE)",
            (self.tenant_id, workspace_id, organization_id, code(warehouse_code, "Warehouse code"), active),
            "Inventory warehouse was not found or inactive.",
        )

    def _location(self, warehouse_id: str, location_code: str, *, active: bool = False) -> dict[str, Any]:
        return self._one(
            "SELECT * FROM reconforge.inventory_locations WHERE tenant_id=%s AND warehouse_id=%s AND location_code=%s AND (%s=FALSE OR active=TRUE)",
            (self.tenant_id, warehouse_id, code(location_code, "Location code"), active),
            "Inventory location was not found or inactive.",
        )

    def upsert_uom(
        self,
        *,
        uom_code: str,
        name: str,
        workspace: str = "default",
        category: str = "Count",
        decimal_places: int = 0,
        active: bool = True,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        unit_code = code(uom_code, "Unit code")
        unit_category = choice(category, "Unit category", UOM_CATEGORIES)
        if isinstance(decimal_places, bool) or not 0 <= decimal_places <= 6:
            raise PlatformError("Unit decimal places must be between 0 and 6.")
        with self._transaction():
            workspace_id = self._workspace_id(workspace)
            existing = self.connection.execute(
                "SELECT * FROM reconforge.inventory_units_of_measure WHERE tenant_id=%s AND workspace_id=%s AND uom_code=%s FOR UPDATE",
                (self.tenant_id, workspace_id, unit_code),
            ).fetchone()
            if existing is not None:
                current = dict(existing) if isinstance(existing, Mapping) else dict(existing)
                used = (
                    self.connection.execute(
                        "SELECT 1 FROM reconforge.inventory_items WHERE tenant_id=%s AND uom_id=%s LIMIT 1",
                        (self.tenant_id, current["id"]),
                    ).fetchone()
                    is not None
                )
                if used and (current["category"] != unit_category or current["decimal_places"] != decimal_places):
                    raise PlatformError("A referenced unit cannot change category or precision.")
                if current["active"] and not active:
                    active_item = self.connection.execute(
                        "SELECT 1 FROM reconforge.inventory_items WHERE tenant_id=%s AND uom_id=%s AND active=TRUE LIMIT 1",
                        (self.tenant_id, current["id"]),
                    ).fetchone()
                    if active_item is not None:
                        raise PlatformError("Deactivate items using this unit before deactivating it.")
                unit_id = str(current["id"])
            else:
                unit_id = platform_id("UOM", workspace_id, unit_code)
            self.connection.execute(
                """INSERT INTO reconforge.inventory_units_of_measure
                (tenant_id,id,workspace_id,uom_code,name,category,decimal_places,active) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(tenant_id,workspace_id,uom_code) DO UPDATE SET name=excluded.name,category=excluded.category,
                decimal_places=excluded.decimal_places,active=excluded.active,updated_at=now(),row_version=inventory_units_of_measure.row_version+1""",
                (
                    self.tenant_id,
                    unit_id,
                    workspace_id,
                    unit_code,
                    clean_text(name, "Unit name"),
                    unit_category,
                    decimal_places,
                    bool(active),
                ),
            )
            result = self._uom(workspace_id, unit_code)
            self._event(
                actor_label=actor_label,
                object_type="inventory_uom",
                object_id=unit_id,
                action="inventory_uom_saved",
                version=result["row_version"],
                metadata={"uom_code": unit_code},
            )
            return public_record(result)

    def list_uoms(
        self, *, workspace: str = "default", limit: int = 500, offset: int = 0, actor_label: str = "local-cli"
    ) -> list[dict[str, Any]]:
        limit, offset = page(limit, offset)
        with self._transaction():
            workspace_id = self._workspace_id(workspace)
            rows = self.connection.execute(
                "SELECT * FROM reconforge.inventory_units_of_measure WHERE tenant_id=%s AND workspace_id=%s ORDER BY uom_code,id LIMIT %s OFFSET %s",
                (self.tenant_id, workspace_id, limit, offset),
            ).fetchall()
            return [public_record(row) for row in rows]

    def upsert_item(
        self,
        *,
        item_code: str,
        name: str,
        workspace: str = "default",
        organization_code: str = "",
        uom_code: str = "EA",
        item_type: str = "Stock",
        tracking_mode: str = "None",
        inventory_account_code: str = "",
        description: str = "",
        active: bool = True,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        item_code = code(item_code, "Item code")
        item_type = choice(item_type, "Item type", ITEM_TYPES)
        tracking_mode = choice(tracking_mode, "Tracking mode", TRACKING_MODES)
        if item_type == "Service" and tracking_mode != "None":
            raise PlatformError("Service items cannot use lot or serial tracking.")
        with self._transaction():
            workspace_id = self._workspace_id(workspace)
            organization = self._organization(workspace_id, organization_code) if organization_code.strip() else None
            uom = self._uom(workspace_id, uom_code, active=True)
            account_id = None
            if inventory_account_code.strip():
                account = self._one(
                    """SELECT a.id,c.organization_code FROM reconforge.finance_accounts a JOIN reconforge.finance_charts c ON c.tenant_id=a.tenant_id AND c.id=a.chart_id WHERE a.tenant_id=%s AND c.workspace_id=%s AND a.account_code=%s AND a.active=TRUE""",
                    (self.tenant_id, workspace_id, code(inventory_account_code, "Inventory account code")),
                    "Inventory account was not found or inactive.",
                )
                if organization is not None and account["organization_code"] not in ("", organization_code.upper()):
                    raise PlatformError("Inventory account belongs to a different organization.")
                account_id = account["id"]
            current_row = self.connection.execute(
                "SELECT * FROM reconforge.inventory_items WHERE tenant_id=%s AND workspace_id=%s AND item_code=%s FOR UPDATE",
                (self.tenant_id, workspace_id, item_code),
            ).fetchone()
            current = dict(current_row) if current_row is not None else None
            item_id = str(current["id"]) if current else platform_id("ITEM", workspace_id, item_code)
            if current:
                used = (
                    self.connection.execute(
                        "SELECT 1 FROM reconforge.inventory_movement_lines WHERE tenant_id=%s AND item_id=%s LIMIT 1",
                        (self.tenant_id, item_id),
                    ).fetchone()
                    is not None
                )
                immutable = (
                    current["organization_id"],
                    current["uom_id"],
                    current["item_type"],
                    current["tracking_mode"],
                )
                proposed = (organization["id"] if organization else None, uom["id"], item_type, tracking_mode)
                if used and immutable != proposed:
                    raise PlatformError("A referenced item cannot change organization, unit, type, or tracking mode.")
                if used and current["active"] and not active:
                    raise PlatformError("A referenced inventory item cannot be deactivated.")
            self.connection.execute(
                """INSERT INTO reconforge.inventory_items(tenant_id,id,workspace_id,organization_id,item_code,name,item_type,tracking_mode,uom_id,inventory_account_id,description,active)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(tenant_id,workspace_id,item_code) DO UPDATE SET organization_id=excluded.organization_id,name=excluded.name,item_type=excluded.item_type,tracking_mode=excluded.tracking_mode,uom_id=excluded.uom_id,inventory_account_id=excluded.inventory_account_id,description=excluded.description,active=excluded.active,updated_at=now(),row_version=inventory_items.row_version+1""",
                (
                    self.tenant_id,
                    item_id,
                    workspace_id,
                    organization["id"] if organization else None,
                    item_code,
                    clean_text(name, "Item name"),
                    item_type,
                    tracking_mode,
                    uom["id"],
                    account_id,
                    clean_text(description, "Item description", maximum=500, required=False),
                    bool(active),
                ),
            )
            result = self._item(workspace_id, item_code)
            self._event(
                actor_label=actor_label,
                object_type="inventory_item",
                object_id=item_id,
                action="inventory_item_saved",
                version=result["row_version"],
                metadata={"item_code": item_code},
            )
            return public_record(result)

    def list_items(
        self,
        *,
        workspace: str = "default",
        organization_code: str = "",
        active_only: bool = False,
        limit: int = 500,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]:
        limit, offset = page(limit, offset)
        with self._transaction():
            workspace_id = self._workspace_id(workspace)
            organization = self._organization(workspace_id, organization_code) if organization_code.strip() else None
            sql = "SELECT i.*,u.uom_code FROM reconforge.inventory_items i JOIN reconforge.inventory_units_of_measure u ON u.tenant_id=i.tenant_id AND u.id=i.uom_id WHERE i.tenant_id=%s AND i.workspace_id=%s"
            params: list[object] = [self.tenant_id, workspace_id]
            if organization:
                sql += " AND i.organization_id=%s"
                params.append(organization["id"])
            if active_only:
                sql += " AND i.active=TRUE"
            sql += " ORDER BY i.item_code,i.id LIMIT %s OFFSET %s"
            params.extend((limit, offset))
            return [public_record(row) for row in self.connection.execute(sql, tuple(params)).fetchall()]

    def on_hand(
        self,
        *,
        organization_code: str,
        entity_code: str,
        workspace: str = "default",
        item_code: str = "",
        warehouse_code: str = "",
        include_zero: bool = False,
        limit: int = 500,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> dict[str, object]:
        limit, offset = page(limit, offset)
        with self._transaction():
            workspace_id = self._workspace_id(workspace)
            organization = self._organization(workspace_id, organization_code)
            entity = self._entity(str(organization["id"]), entity_code)
            if entity is None:
                raise PlatformError("Inventory on-hand requires a legal entity.")
            sql = """WITH stock AS (
              SELECT l.to_location_id location_id,l.item_id,l.inventory_lot_id,l.uom_id,l.quantity_precision,l.quantity_scaled delta
              FROM reconforge.inventory_movement_lines l JOIN reconforge.inventory_movements m ON m.tenant_id=l.tenant_id AND m.id=l.movement_id
              WHERE l.tenant_id=%s AND m.workspace_id=%s AND m.organization_id=%s AND m.legal_entity_id=%s AND m.status='Posted' AND l.to_location_id IS NOT NULL
              UNION ALL
              SELECT l.from_location_id,l.item_id,l.inventory_lot_id,l.uom_id,l.quantity_precision,-l.quantity_scaled
              FROM reconforge.inventory_movement_lines l JOIN reconforge.inventory_movements m ON m.tenant_id=l.tenant_id AND m.id=l.movement_id
              WHERE l.tenant_id=%s AND m.workspace_id=%s AND m.organization_id=%s AND m.legal_entity_id=%s AND m.status='Posted' AND l.from_location_id IS NOT NULL)
              SELECT s.location_id,w.warehouse_code,loc.location_code,loc.allow_negative,s.item_id,i.item_code,i.name item_name,u.uom_code,
              s.inventory_lot_id,lot.lot_serial_code,s.quantity_precision,SUM(s.delta) quantity_scaled
              FROM stock s JOIN reconforge.inventory_locations loc ON loc.tenant_id=%s AND loc.id=s.location_id
              JOIN reconforge.inventory_warehouses w ON w.tenant_id=%s AND w.id=loc.warehouse_id
              JOIN reconforge.inventory_items i ON i.tenant_id=%s AND i.id=s.item_id
              JOIN reconforge.inventory_units_of_measure u ON u.tenant_id=%s AND u.id=s.uom_id
              LEFT JOIN reconforge.inventory_lots lot ON lot.tenant_id=%s AND lot.id=s.inventory_lot_id WHERE TRUE"""
            params: list[object] = [
                self.tenant_id,
                workspace_id,
                organization["id"],
                entity["id"],
                self.tenant_id,
                workspace_id,
                organization["id"],
                entity["id"],
                self.tenant_id,
                self.tenant_id,
                self.tenant_id,
                self.tenant_id,
                self.tenant_id,
            ]
            if item_code.strip():
                sql += " AND i.item_code=%s"
                params.append(code(item_code, "Item code"))
            if warehouse_code.strip():
                sql += " AND w.warehouse_code=%s"
                params.append(code(warehouse_code, "Warehouse code"))
            sql += " GROUP BY s.location_id,w.warehouse_code,loc.location_code,loc.allow_negative,s.item_id,i.item_code,i.name,u.uom_code,s.inventory_lot_id,lot.lot_serial_code,s.quantity_precision"
            if not include_zero:
                sql += " HAVING SUM(s.delta)<>0"
            sql += " ORDER BY w.warehouse_code,loc.location_code,i.item_code,lot.lot_serial_code NULLS FIRST,s.inventory_lot_id LIMIT %s OFFSET %s"
            params.extend((limit, offset))
            records: list[dict[str, Any]] = []
            negative_count = 0
            for row in self.connection.execute(sql, tuple(params)).fetchall():
                record = public_record(row)
                quantity = int(record["quantity_scaled"])
                record["quantity"] = scaled_to_text(quantity, int(record["quantity_precision"]))
                record["negative"] = quantity < 0
                negative_count += int(quantity < 0)
                records.append(record)
            return {
                "schema_version": 1,
                "source": {"kind": "local-inventory-ledger", "local_first": True, "external_calls": False},
                "workspace": clean_text(workspace, "Workspace name"),
                "organization_code": organization["organization_code"],
                "entity_code": entity["entity_code"],
                "summary": {"rows": len(records), "negative_rows": negative_count},
                "balances": records,
            }

    def control_exceptions(
        self,
        *,
        organization_code: str,
        entity_code: str,
        workspace: str = "default",
        as_of: str = "",
        actor_label: str = "local-cli",
    ) -> dict[str, object]:
        as_of_date = iso_date(as_of, "As-of date", required=False) or utc_today()
        balances = self.on_hand(
            workspace=workspace,
            organization_code=organization_code,
            entity_code=entity_code,
            include_zero=False,
            limit=MAX_LIST_LIMIT,
            actor_label=actor_label,
        )
        balance_rows = balances["balances"]
        if not isinstance(balance_rows, list):
            raise PlatformError("Unable to read inventory balances for control evaluation.")
        exceptions: list[dict[str, object]] = []
        with self._transaction():
            for balance in balance_rows:
                if not isinstance(balance, dict):
                    continue
                if int(balance["quantity_scaled"]) < 0:
                    key = f"{balance['warehouse_code']}|{balance['location_code']}|{balance['item_code']}|{balance.get('lot_serial_code') or ''}"
                    exceptions.append(
                        {
                            "exception_id": platform_id("INVEX", "NEGATIVE_STOCK", key),
                            "control_code": "INV-NEGATIVE-STOCK",
                            "risk_rating": "high",
                            "item_code": balance["item_code"],
                            "warehouse_code": balance["warehouse_code"],
                            "location_code": balance["location_code"],
                            "lot_serial_code": balance.get("lot_serial_code"),
                            "quantity": balance["quantity"],
                            "description": "Posted local movements produce a negative on-hand quantity.",
                        }
                    )
                if balance.get("inventory_lot_id") and int(balance["quantity_scaled"]) > 0:
                    lot = self.connection.execute(
                        "SELECT expires_on FROM reconforge.inventory_lots WHERE tenant_id=%s AND id=%s",
                        (self.tenant_id, balance["inventory_lot_id"]),
                    ).fetchone()
                    if lot is not None and lot["expires_on"] is not None and lot["expires_on"] < as_of_date:
                        key = f"{balance['item_code']}|{balance.get('lot_serial_code')}|{balance['location_id']}"
                        exceptions.append(
                            {
                                "exception_id": platform_id("INVEX", "EXPIRED_STOCK", key),
                                "control_code": "INV-EXPIRED-STOCK",
                                "risk_rating": "high",
                                "item_code": balance["item_code"],
                                "warehouse_code": balance["warehouse_code"],
                                "location_code": balance["location_code"],
                                "lot_serial_code": balance.get("lot_serial_code"),
                                "quantity": balance["quantity"],
                                "description": "Positive local on-hand quantity is assigned to an expired tracked lot.",
                            }
                        )
            workspace_id = self._workspace_id(workspace)
            organization = self._organization(workspace_id, organization_code)
            missing = self.connection.execute(
                "SELECT item_code FROM reconforge.inventory_items WHERE tenant_id=%s AND workspace_id=%s AND active=TRUE AND item_type='Stock' AND inventory_account_id IS NULL AND (organization_id IS NULL OR organization_id=%s) ORDER BY item_code",
                (self.tenant_id, workspace_id, organization["id"]),
            ).fetchall()
            for item in missing:
                exceptions.append(
                    {
                        "exception_id": platform_id("INVEX", "MISSING_ACCOUNT", item["item_code"]),
                        "control_code": "INV-MISSING-ACCOUNT",
                        "risk_rating": "medium",
                        "item_code": item["item_code"],
                        "warehouse_code": None,
                        "location_code": None,
                        "lot_serial_code": None,
                        "quantity": None,
                        "description": "Active stock item has no local inventory account reference.",
                    }
                )
        exceptions.sort(
            key=lambda item: (str(item["risk_rating"]), str(item["control_code"]), str(item["exception_id"]))
        )
        return {
            "schema_version": 1,
            "generated_at": utc_now_text(),
            "as_of": as_of_date.isoformat(),
            "source": {"kind": "local-inventory-controls", "local_first": True, "external_calls": False},
            "workspace": clean_text(workspace, "Workspace name"),
            "organization_code": code(organization_code, "Organization code"),
            "entity_code": code(entity_code, "Entity code"),
            "summary": {
                "total": len(exceptions),
                "high": sum(item["risk_rating"] == "high" for item in exceptions),
                "medium": sum(item["risk_rating"] == "medium" for item in exceptions),
            },
            "exceptions": exceptions,
        }

    def summary(self, *, workspace: str = "default", actor_label: str = "local-cli") -> InventoryCoreSummary:
        workspace_name = clean_text(workspace, "Workspace name")
        with self._transaction():
            workspace_id = self._workspace_id(workspace_name)
            row = self.connection.execute(
                """SELECT
              (SELECT COUNT(*) FROM reconforge.inventory_units_of_measure WHERE tenant_id=%s AND workspace_id=%s) units,
              (SELECT COUNT(*) FROM reconforge.inventory_items WHERE tenant_id=%s AND workspace_id=%s) items,
              (SELECT COUNT(*) FROM reconforge.inventory_warehouses WHERE tenant_id=%s AND workspace_id=%s) warehouses,
              (SELECT COUNT(*) FROM reconforge.inventory_locations l JOIN reconforge.inventory_warehouses w ON w.tenant_id=l.tenant_id AND w.id=l.warehouse_id WHERE l.tenant_id=%s AND w.workspace_id=%s) locations,
              (SELECT COUNT(*) FROM reconforge.inventory_lots WHERE tenant_id=%s AND workspace_id=%s) lots,
              (SELECT COUNT(*) FROM reconforge.inventory_movements WHERE tenant_id=%s AND workspace_id=%s AND status='Draft') drafts,
              (SELECT COUNT(*) FROM reconforge.inventory_movements WHERE tenant_id=%s AND workspace_id=%s AND status='Posted') posted,
              (SELECT COUNT(*) FROM reconforge.inventory_movements WHERE tenant_id=%s AND workspace_id=%s AND status='Voided') voided""",
                (self.tenant_id, workspace_id) * 8,
            ).fetchone()
            return InventoryCoreSummary(
                workspace_name,
                *(
                    int(row[field])
                    for field in ("units", "items", "warehouses", "locations", "lots", "drafts", "posted", "voided")
                ),
            )

    def snapshot(self, *, workspace: str = "default", actor_label: str = "local-cli") -> dict[str, object]:
        workspace_name = clean_text(workspace, "Workspace name")
        summary = self.summary(workspace=workspace_name, actor_label=actor_label)
        counts = (
            summary.units_of_measure,
            summary.items,
            summary.warehouses,
            summary.locations,
            summary.lots_and_serials,
            summary.draft_movements + summary.posted_movements + summary.voided_movements,
        )
        if any(count > MAX_LIST_LIMIT for count in counts):
            raise PlatformError(f"Inventory-core snapshot is limited to {MAX_LIST_LIMIT} records per collection.")
        return {
            "schema_version": 1,
            "generated_at": utc_now_text(),
            "source": {"kind": "local-inventory-core", "local_first": True, "external_calls": False},
            "workspace": workspace_name,
            "summary": summary.to_dict(),
            "units_of_measure": self.list_uoms(workspace=workspace_name, limit=MAX_LIST_LIMIT, actor_label=actor_label),
            "items": self.list_items(workspace=workspace_name, limit=MAX_LIST_LIMIT, actor_label=actor_label),
            "warehouses": self.list_warehouses(workspace=workspace_name, limit=MAX_LIST_LIMIT, actor_label=actor_label),
            "locations": self.list_locations(workspace=workspace_name, limit=MAX_LIST_LIMIT, actor_label=actor_label),
            "lots_and_serials": self.list_lots(workspace=workspace_name, limit=MAX_LIST_LIMIT, actor_label=actor_label),
            "movements": self.list_movements(workspace=workspace_name, limit=MAX_LIST_LIMIT, actor_label=actor_label),
        }

    def upsert_warehouse(
        self,
        *,
        warehouse_code: str,
        name: str,
        organization_code: str,
        workspace: str = "default",
        entity_code: str = "",
        active: bool = True,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        warehouse_code = code(warehouse_code, "Warehouse code")
        with self._transaction():
            workspace_id = self._workspace_id(workspace)
            organization = self._organization(workspace_id, organization_code)
            entity = self._entity(str(organization["id"]), entity_code)
            row = self.connection.execute(
                "SELECT * FROM reconforge.inventory_warehouses WHERE tenant_id=%s AND workspace_id=%s AND organization_id=%s AND warehouse_code=%s FOR UPDATE",
                (self.tenant_id, workspace_id, organization["id"], warehouse_code),
            ).fetchone()
            current = dict(row) if row is not None else None
            warehouse_id = (
                str(current["id"]) if current else platform_id("WH", workspace_id, organization["id"], warehouse_code)
            )
            if (
                current
                and self.connection.execute(
                    "SELECT 1 FROM reconforge.inventory_locations WHERE tenant_id=%s AND warehouse_id=%s LIMIT 1",
                    (self.tenant_id, warehouse_id),
                ).fetchone()
                is not None
                and current["legal_entity_id"] != (entity["id"] if entity else None)
            ):
                raise PlatformError("A referenced warehouse cannot change legal entity.")
            if (
                current
                and current["active"]
                and not active
                and self.connection.execute(
                    "SELECT 1 FROM reconforge.inventory_locations WHERE tenant_id=%s AND warehouse_id=%s AND active=TRUE LIMIT 1",
                    (self.tenant_id, warehouse_id),
                ).fetchone()
                is not None
            ):
                raise PlatformError("Deactivate warehouse locations before deactivating the warehouse.")
            self.connection.execute(
                """INSERT INTO reconforge.inventory_warehouses(tenant_id,id,workspace_id,organization_id,legal_entity_id,warehouse_code,name,active) VALUES(%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(tenant_id,workspace_id,organization_id,warehouse_code) DO UPDATE SET legal_entity_id=excluded.legal_entity_id,name=excluded.name,active=excluded.active,updated_at=now(),row_version=inventory_warehouses.row_version+1""",
                (
                    self.tenant_id,
                    warehouse_id,
                    workspace_id,
                    organization["id"],
                    entity["id"] if entity else None,
                    warehouse_code,
                    clean_text(name, "Warehouse name"),
                    bool(active),
                ),
            )
            result = self._warehouse(workspace_id, str(organization["id"]), warehouse_code)
            self._event(
                actor_label=actor_label,
                object_type="inventory_warehouse",
                object_id=warehouse_id,
                action="inventory_warehouse_saved",
                version=result["row_version"],
                metadata={"warehouse_code": warehouse_code},
            )
            return public_record(result)

    def list_warehouses(
        self,
        *,
        workspace: str = "default",
        organization_code: str = "",
        limit: int = 500,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]:
        limit, offset = page(limit, offset)
        with self._transaction():
            workspace_id = self._workspace_id(workspace)
            params: list[object] = [self.tenant_id, workspace_id]
            sql = "SELECT * FROM reconforge.inventory_warehouses WHERE tenant_id=%s AND workspace_id=%s"
            if organization_code.strip():
                organization = self._organization(workspace_id, organization_code)
                sql += " AND organization_id=%s"
                params.append(organization["id"])
            sql += " ORDER BY warehouse_code,id LIMIT %s OFFSET %s"
            params.extend((limit, offset))
            return [public_record(row) for row in self.connection.execute(sql, tuple(params)).fetchall()]

    def upsert_location(
        self,
        *,
        warehouse_code: str,
        location_code: str,
        name: str,
        organization_code: str,
        workspace: str = "default",
        parent_location_code: str = "",
        location_type: str = "Internal",
        allow_negative: bool = False,
        active: bool = True,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        location_code = code(location_code, "Location code")
        location_type = choice(location_type, "Location type", LOCATION_TYPES)
        with self._transaction():
            workspace_id = self._workspace_id(workspace)
            organization = self._organization(workspace_id, organization_code)
            warehouse = self._warehouse(workspace_id, str(organization["id"]), warehouse_code, active=True)
            row = self.connection.execute(
                "SELECT * FROM reconforge.inventory_locations WHERE tenant_id=%s AND warehouse_id=%s AND location_code=%s FOR UPDATE",
                (self.tenant_id, warehouse["id"], location_code),
            ).fetchone()
            current = dict(row) if row is not None else None
            location_id = str(current["id"]) if current else platform_id("LOC", warehouse["id"], location_code)
            parent_id = None
            if parent_location_code.strip():
                parent = self._location(str(warehouse["id"]), parent_location_code)
                parent_id = str(parent["id"])
                if parent_id == location_id:
                    raise PlatformError("An inventory location cannot be its own parent.")
                cycle = self.connection.execute(
                    """WITH RECURSIVE descendants(id) AS (
                    SELECT id FROM reconforge.inventory_locations WHERE tenant_id=%s AND parent_location_id=%s
                    UNION ALL SELECT l.id FROM reconforge.inventory_locations l JOIN descendants d ON l.parent_location_id=d.id WHERE l.tenant_id=%s)
                    SELECT 1 FROM descendants WHERE id=%s LIMIT 1""",
                    (self.tenant_id, location_id, self.tenant_id, parent_id),
                ).fetchone()
                if cycle is not None:
                    raise PlatformError("Inventory location hierarchy must remain acyclic.")
            referenced = (
                self.connection.execute(
                    "SELECT 1 FROM reconforge.inventory_movement_lines WHERE tenant_id=%s AND (from_location_id=%s OR to_location_id=%s) LIMIT 1",
                    (self.tenant_id, location_id, location_id),
                ).fetchone()
                is not None
            )
            if (
                current
                and referenced
                and (current["parent_location_id"], current["location_type"], current["allow_negative"])
                != (parent_id, location_type, bool(allow_negative))
            ):
                raise PlatformError("A referenced location cannot change parent, type, or negative-stock policy.")
            if referenced and not active:
                raise PlatformError("Locations referenced by inventory movements cannot be deactivated.")
            if current and not allow_negative:
                negative = self.connection.execute(
                    """SELECT 1 FROM (SELECT l.item_id,l.inventory_lot_id,
                    SUM(CASE WHEN l.to_location_id=%s THEN l.quantity_scaled ELSE 0 END)-SUM(CASE WHEN l.from_location_id=%s THEN l.quantity_scaled ELSE 0 END) balance
                    FROM reconforge.inventory_movement_lines l JOIN reconforge.inventory_movements m ON m.tenant_id=l.tenant_id AND m.id=l.movement_id
                    WHERE l.tenant_id=%s AND m.status='Posted' AND (l.to_location_id=%s OR l.from_location_id=%s) GROUP BY l.item_id,l.inventory_lot_id) b WHERE balance<0 LIMIT 1""",
                    (location_id, location_id, self.tenant_id, location_id, location_id),
                ).fetchone()
                if negative is not None:
                    raise PlatformError("This location currently has negative stock and cannot disallow it.")
            self.connection.execute(
                """INSERT INTO reconforge.inventory_locations(tenant_id,id,warehouse_id,parent_location_id,location_code,name,location_type,allow_negative,active)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(tenant_id,warehouse_id,location_code) DO UPDATE SET parent_location_id=excluded.parent_location_id,name=excluded.name,location_type=excluded.location_type,allow_negative=excluded.allow_negative,active=excluded.active,updated_at=now(),row_version=inventory_locations.row_version+1""",
                (
                    self.tenant_id,
                    location_id,
                    warehouse["id"],
                    parent_id,
                    location_code,
                    clean_text(name, "Location name"),
                    location_type,
                    bool(allow_negative),
                    bool(active),
                ),
            )
            result = self._location(str(warehouse["id"]), location_code)
            self._event(
                actor_label=actor_label,
                object_type="inventory_location",
                object_id=location_id,
                action="inventory_location_saved",
                version=result["row_version"],
                metadata={
                    "warehouse_code": warehouse_code,
                    "location_code": location_code,
                    "allow_negative": bool(allow_negative),
                },
            )
            return public_record(result)

    def list_locations(
        self,
        *,
        workspace: str = "default",
        organization_code: str = "",
        warehouse_code: str = "",
        limit: int = 500,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]:
        limit, offset = page(limit, offset)
        with self._transaction():
            workspace_id = self._workspace_id(workspace)
            sql = """SELECT l.*,w.warehouse_code,o.organization_code,p.location_code parent_location_code FROM reconforge.inventory_locations l JOIN reconforge.inventory_warehouses w ON w.tenant_id=l.tenant_id AND w.id=l.warehouse_id JOIN reconforge.organizations o ON o.tenant_id=w.tenant_id AND o.id=w.organization_id LEFT JOIN reconforge.inventory_locations p ON p.tenant_id=l.tenant_id AND p.id=l.parent_location_id WHERE l.tenant_id=%s AND w.workspace_id=%s"""
            params: list[object] = [self.tenant_id, workspace_id]
            if organization_code.strip():
                sql += " AND o.organization_code=%s"
                params.append(code(organization_code, "Organization code"))
            if warehouse_code.strip():
                sql += " AND w.warehouse_code=%s"
                params.append(code(warehouse_code, "Warehouse code"))
            sql += " ORDER BY o.organization_code,w.warehouse_code,l.location_code,l.id LIMIT %s OFFSET %s"
            params.extend((limit, offset))
            return [public_record(row) for row in self.connection.execute(sql, tuple(params)).fetchall()]

    def upsert_lot(
        self,
        *,
        item_code: str,
        lot_serial_code: str,
        organization_code: str,
        workspace: str = "default",
        manufactured_on: str = "",
        expires_on: str = "",
        active: bool = True,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        with self._transaction():
            workspace_id = self._workspace_id(workspace)
            organization = self._organization(workspace_id, organization_code)
            item = self._item(workspace_id, item_code, active=True)
            if item["organization_id"] is not None and item["organization_id"] != organization["id"]:
                raise PlatformError("Tracked item belongs to a different organization.")
            if item["tracking_mode"] not in ("Lot", "Serial"):
                raise PlatformError("Lot/serial references require an item configured for Lot or Serial tracking.")
            lot_code = code(lot_serial_code, "Lot/serial code")
            manufactured = iso_date(manufactured_on, "Manufacture date", required=False)
            expires = iso_date(expires_on, "Expiry date", required=False)
            if manufactured and expires and manufactured > expires:
                raise PlatformError("Expiry date cannot be earlier than manufacture date.")
            lot_id = platform_id("LOT", item["id"], organization["id"], lot_code)
            row = self.connection.execute(
                "SELECT * FROM reconforge.inventory_lots WHERE tenant_id=%s AND item_id=%s AND organization_id=%s AND lot_serial_code=%s FOR UPDATE",
                (self.tenant_id, item["id"], organization["id"], lot_code),
            ).fetchone()
            current = dict(row) if row is not None else None
            referenced = (
                self.connection.execute(
                    "SELECT 1 FROM reconforge.inventory_movement_lines WHERE tenant_id=%s AND inventory_lot_id=%s LIMIT 1",
                    (self.tenant_id, lot_id),
                ).fetchone()
                is not None
            )
            if (
                current
                and referenced
                and (current["manufactured_on"], current["expires_on"]) != (manufactured, expires)
            ):
                raise PlatformError("A referenced lot or serial cannot change its dates.")
            if referenced and not active:
                raise PlatformError("Lots or serials referenced by inventory movements cannot be deactivated.")
            self.connection.execute(
                """INSERT INTO reconforge.inventory_lots(tenant_id,id,workspace_id,organization_id,item_id,lot_serial_code,tracking_type,manufactured_on,expires_on,active) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(tenant_id,item_id,organization_id,lot_serial_code) DO UPDATE SET manufactured_on=excluded.manufactured_on,expires_on=excluded.expires_on,active=excluded.active,updated_at=now(),row_version=inventory_lots.row_version+1""",
                (
                    self.tenant_id,
                    lot_id,
                    workspace_id,
                    organization["id"],
                    item["id"],
                    lot_code,
                    item["tracking_mode"],
                    manufactured,
                    expires,
                    bool(active),
                ),
            )
            result = self._one(
                "SELECT * FROM reconforge.inventory_lots WHERE tenant_id=%s AND id=%s",
                (self.tenant_id, lot_id),
                "Inventory lot or serial was not found.",
            )
            self._event(
                actor_label=actor_label,
                object_type="inventory_lot",
                object_id=lot_id,
                action="inventory_lot_saved",
                version=result["row_version"],
                metadata={"item_code": item_code, "lot_serial_code": lot_code},
            )
            return public_record(result)

    def list_lots(
        self,
        *,
        workspace: str = "default",
        organization_code: str = "",
        item_code: str = "",
        limit: int = 500,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]:
        limit, offset = page(limit, offset)
        with self._transaction():
            workspace_id = self._workspace_id(workspace)
            sql = """SELECT l.*,i.item_code,o.organization_code FROM reconforge.inventory_lots l JOIN reconforge.inventory_items i ON i.tenant_id=l.tenant_id AND i.id=l.item_id JOIN reconforge.organizations o ON o.tenant_id=l.tenant_id AND o.id=l.organization_id WHERE l.tenant_id=%s AND l.workspace_id=%s"""
            params: list[object] = [self.tenant_id, workspace_id]
            if organization_code.strip():
                sql += " AND o.organization_code=%s"
                params.append(code(organization_code, "Organization code"))
            if item_code.strip():
                sql += " AND i.item_code=%s"
                params.append(code(item_code, "Item code"))
            sql += " ORDER BY i.item_code,l.lot_serial_code,l.id LIMIT %s OFFSET %s"
            params.extend((limit, offset))
            return [public_record(row) for row in self.connection.execute(sql, tuple(params)).fetchall()]

    def _period(self, workspace_id: str, period_id: str) -> dict[str, Any]:
        return self._one(
            """SELECT p.* FROM reconforge.fiscal_periods p
            JOIN reconforge.master_data_workspace_periods w ON w.tenant_id=p.tenant_id AND w.period_id=p.id
            WHERE p.tenant_id=%s AND w.workspace_id=%s AND p.id=%s""",
            (self.tenant_id, workspace_id, clean_text(period_id, "Period identifier")),
            "Fiscal-period reference was not found.",
        )

    def _lot(self, item_id: str, organization_id: str, lot_code: str) -> dict[str, Any]:
        return self._one(
            "SELECT * FROM reconforge.inventory_lots WHERE tenant_id=%s AND item_id=%s AND organization_id=%s AND lot_serial_code=%s",
            (self.tenant_id, item_id, organization_id, code(lot_code, "Lot/serial code")),
            "Lot or serial reference was not found.",
        )

    def _location_reference(
        self, workspace_id: str, organization_id: str, entity_id: str, value: object
    ) -> dict[str, Any] | None:
        reference = clean_text(value, "Location reference", maximum=129, required=False)
        if not reference:
            return None
        parts = reference.split("/")
        if len(parts) != 2:
            raise PlatformError("Location references must use WAREHOUSE/LOCATION format.")
        warehouse = self._warehouse(workspace_id, organization_id, parts[0], active=True)
        if warehouse["legal_entity_id"] is not None and warehouse["legal_entity_id"] != entity_id:
            raise PlatformError("Movement warehouse belongs to a different legal entity.")
        location = self._location(str(warehouse["id"]), parts[1], active=True)
        location["warehouse_code"] = warehouse["warehouse_code"]
        return location

    @staticmethod
    def _validate_direction(
        movement_type: str, source: Mapping[str, object] | None, destination: Mapping[str, object] | None
    ) -> None:
        if source is not None and destination is not None and source["id"] == destination["id"]:
            raise PlatformError("Inventory movement source and destination locations must differ.")
        valid = (
            (movement_type == "Receipt" and source is None and destination is not None)
            or (movement_type == "Delivery" and source is not None and destination is None)
            or (movement_type == "Transfer" and source is not None and destination is not None)
            or (movement_type == "Adjustment" and (source is None) != (destination is None))
        )
        if not valid:
            raise PlatformError(
                "Receipt lines require only a destination; Delivery only a source; Transfer both; Adjustment exactly one."
            )

    def create_movement(
        self,
        *,
        movement_number: str,
        movement_type: str,
        organization_code: str,
        entity_code: str,
        period_id: str,
        movement_date: str,
        description: str,
        lines: Sequence[Mapping[str, object]],
        workspace: str = "default",
        source_reference: str = "",
        source_type: str = "Manual",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        number = normalize_movement_number(movement_number)
        selected_type = choice(movement_type, "Movement type", MOVEMENT_TYPES)
        selected_source = choice(source_type, "Movement source type", MOVEMENT_SOURCE_TYPES)
        moved_on = iso_date(movement_date, "Movement date")
        if moved_on is None or not 1 <= len(lines) <= MAX_MOVEMENT_LINES:
            raise PlatformError(f"Inventory movements require between 1 and {MAX_MOVEMENT_LINES} lines.")
        with self._transaction():
            workspace_id = self._workspace_id(workspace)
            organization = self._organization(workspace_id, organization_code)
            entity = self._entity(str(organization["id"]), entity_code)
            if entity is None:
                raise PlatformError("Inventory movements require a legal entity.")
            period = self._period(workspace_id, period_id)
            start, end = (
                iso_date(period["start_date"], "Stored period start date"),
                iso_date(period["end_date"], "Stored period end date"),
            )
            if period["status"] != "Open" or start is None or end is None or not start <= moved_on <= end:
                raise PlatformError("Inventory movements require an Open fiscal period containing the movement date.")
            prepared: list[dict[str, Any]] = []
            serials: set[str] = set()
            for line_number, line in enumerate(lines, 1):
                if not isinstance(line, Mapping):
                    raise PlatformError("Each inventory movement line must be an object.")
                item = self._item(workspace_id, code(line.get("item_code"), "Item code"), active=True)
                if item["item_type"] == "Service" or (
                    item["organization_id"] is not None and item["organization_id"] != organization["id"]
                ):
                    raise PlatformError(
                        "Movement lines require an active stock or consumable item in the same organization."
                    )
                quantity = quantity_to_scaled(line.get("quantity"), int(item["decimal_places"]), "Line quantity")
                source = self._location_reference(
                    workspace_id, str(organization["id"]), str(entity["id"]), line.get("from_location")
                )
                destination = self._location_reference(
                    workspace_id, str(organization["id"]), str(entity["id"]), line.get("to_location")
                )
                self._validate_direction(selected_type, source, destination)
                lot = None
                lot_code = clean_text(line.get("lot_serial_code", ""), "Lot/serial code", maximum=64, required=False)
                if item["tracking_mode"] == "None" and lot_code:
                    raise PlatformError("Untracked items cannot carry a lot or serial reference.")
                if item["tracking_mode"] != "None":
                    if not lot_code:
                        raise PlatformError("Tracked movement items require a lot or serial reference.")
                    lot = self._lot(str(item["id"]), str(organization["id"]), lot_code)
                    if not lot["active"] or lot["tracking_type"] != item["tracking_mode"]:
                        raise PlatformError(
                            "Movement line requires an active lot/serial matching the item's tracking mode."
                        )
                    if item["tracking_mode"] == "Serial":
                        if quantity != 10 ** int(item["decimal_places"]):
                            raise PlatformError("A serial-tracked movement line must contain exactly one unit.")
                        if str(lot["id"]) in serials:
                            raise PlatformError("A serial number can appear only once in one inventory movement.")
                        serials.add(str(lot["id"]))
                prepared.append(
                    {
                        "line_number": line_number,
                        "item_id": item["id"],
                        "uom_id": item["uom_id"],
                        "inventory_lot_id": lot["id"] if lot else None,
                        "from_location_id": source["id"] if source else None,
                        "to_location_id": destination["id"] if destination else None,
                        "quantity_scaled": quantity,
                        "quantity_precision": item["decimal_places"],
                        "description": clean_text(
                            line.get("description", ""), "Line description", maximum=500, required=False
                        ),
                    }
                )
            movement_id = platform_id("MOV", workspace_id, number)
            existing = self.connection.execute(
                "SELECT status,created_by,created_at FROM reconforge.inventory_movements WHERE tenant_id=%s AND id=%s FOR UPDATE",
                (self.tenant_id, movement_id),
            ).fetchone()
            if existing is not None and existing["status"] != "Draft":
                raise PlatformError("Only Draft inventory movements can be replaced.")
            creator = existing["created_by"] if existing is not None else clean_text(actor_label, "Actor label")
            if existing is not None:
                self.connection.execute(
                    "DELETE FROM reconforge.inventory_movement_lines WHERE tenant_id=%s AND movement_id=%s",
                    (self.tenant_id, movement_id),
                )
            self.connection.execute(
                """INSERT INTO reconforge.inventory_movements(tenant_id,id,workspace_id,organization_id,legal_entity_id,period_id,movement_number,movement_type,movement_date,source_reference,description,source_type,status,created_by) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'Draft',%s) ON CONFLICT(tenant_id,workspace_id,movement_number) DO UPDATE SET organization_id=excluded.organization_id,legal_entity_id=excluded.legal_entity_id,period_id=excluded.period_id,movement_type=excluded.movement_type,movement_date=excluded.movement_date,source_reference=excluded.source_reference,description=excluded.description,source_type=excluded.source_type,updated_at=now(),row_version=inventory_movements.row_version+1""",
                (
                    self.tenant_id,
                    movement_id,
                    workspace_id,
                    organization["id"],
                    entity["id"],
                    period["id"],
                    number,
                    selected_type,
                    moved_on,
                    clean_text(source_reference, "Source reference", maximum=160, required=False),
                    clean_text(description, "Movement description", maximum=500),
                    selected_source,
                    creator,
                ),
            )
            for line in prepared:
                self.connection.execute(
                    """INSERT INTO reconforge.inventory_movement_lines(tenant_id,id,movement_id,line_number,item_id,uom_id,inventory_lot_id,from_location_id,to_location_id,quantity_scaled,quantity_precision,description) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        self.tenant_id,
                        platform_id("MOVL", movement_id, line["line_number"]),
                        movement_id,
                        *line.values(),
                    ),
                )
            self._event(
                actor_label=actor_label,
                object_type="inventory_movement",
                object_id=movement_id,
                action="inventory_movement_draft_saved",
                version=len(prepared),
                metadata={"movement_number": number, "movement_type": selected_type, "line_count": len(prepared)},
            )
            return self._get_movement(movement_id)

    def _get_movement(self, movement_id: str, *, lock: bool = False) -> dict[str, Any]:
        query = """SELECT m.*,o.organization_code,e.entity_code,p.name period_name
            FROM reconforge.inventory_movements m JOIN reconforge.organizations o ON o.tenant_id=m.tenant_id AND o.id=m.organization_id
            JOIN reconforge.legal_entities e ON e.tenant_id=m.tenant_id AND e.id=m.legal_entity_id
            JOIN reconforge.fiscal_periods p ON p.tenant_id=m.tenant_id AND p.id=m.period_id
            WHERE m.tenant_id=%s AND m.id=%s"""
        if lock:
            query = """SELECT m.*,o.organization_code,e.entity_code,p.name period_name
                FROM reconforge.inventory_movements m JOIN reconforge.organizations o ON o.tenant_id=m.tenant_id AND o.id=m.organization_id
                JOIN reconforge.legal_entities e ON e.tenant_id=m.tenant_id AND e.id=m.legal_entity_id
                JOIN reconforge.fiscal_periods p ON p.tenant_id=m.tenant_id AND p.id=m.period_id
                WHERE m.tenant_id=%s AND m.id=%s FOR UPDATE OF m"""
        movement = self._one(
            query,
            (self.tenant_id, clean_text(movement_id, "Movement identifier")),
            "Inventory movement reference was not found.",
        )
        rows = self.connection.execute(
            """SELECT l.*,i.item_code,i.name item_name,u.uom_code,lot.lot_serial_code,
            fw.warehouse_code from_warehouse_code,fl.location_code from_location_code,
            tw.warehouse_code to_warehouse_code,tl.location_code to_location_code
            FROM reconforge.inventory_movement_lines l JOIN reconforge.inventory_items i ON i.tenant_id=l.tenant_id AND i.id=l.item_id
            JOIN reconforge.inventory_units_of_measure u ON u.tenant_id=l.tenant_id AND u.id=l.uom_id
            LEFT JOIN reconforge.inventory_lots lot ON lot.tenant_id=l.tenant_id AND lot.id=l.inventory_lot_id
            LEFT JOIN reconforge.inventory_locations fl ON fl.tenant_id=l.tenant_id AND fl.id=l.from_location_id
            LEFT JOIN reconforge.inventory_warehouses fw ON fw.tenant_id=l.tenant_id AND fw.id=fl.warehouse_id
            LEFT JOIN reconforge.inventory_locations tl ON tl.tenant_id=l.tenant_id AND tl.id=l.to_location_id
            LEFT JOIN reconforge.inventory_warehouses tw ON tw.tenant_id=l.tenant_id AND tw.id=tl.warehouse_id
            WHERE l.tenant_id=%s AND l.movement_id=%s ORDER BY l.line_number,l.id""",
            (self.tenant_id, movement_id),
        ).fetchall()
        lines = []
        for row in rows:
            record = dict(row)
            record["quantity"] = scaled_to_text(int(record["quantity_scaled"]), int(record["quantity_precision"]))
            record["from_location"] = (
                ""
                if record["from_location_code"] is None
                else f"{record['from_warehouse_code']}/{record['from_location_code']}"
            )
            record["to_location"] = (
                ""
                if record["to_location_code"] is None
                else f"{record['to_warehouse_code']}/{record['to_location_code']}"
            )
            for field in ("from_warehouse_code", "from_location_code", "to_warehouse_code", "to_location_code"):
                record.pop(field)
            lines.append(record)
        movement["line_count"] = len(lines)
        movement["lines"] = lines
        return public_record(movement)

    def get_movement(self, movement_id: str, *, actor_label: str = "local-cli") -> dict[str, Any]:
        with self._transaction():
            return self._get_movement(movement_id)

    def _stock_lines(self, movement_id: str) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """SELECT l.*,i.tracking_mode,
            COALESCE(fl.allow_negative,FALSE) from_allow_negative,COALESCE(tl.allow_negative,FALSE) to_allow_negative
            FROM reconforge.inventory_movement_lines l JOIN reconforge.inventory_items i ON i.tenant_id=l.tenant_id AND i.id=l.item_id
            LEFT JOIN reconforge.inventory_locations fl ON fl.tenant_id=l.tenant_id AND fl.id=l.from_location_id
            LEFT JOIN reconforge.inventory_locations tl ON tl.tenant_id=l.tenant_id AND tl.id=l.to_location_id
            WHERE l.tenant_id=%s AND l.movement_id=%s ORDER BY l.line_number,l.id""",
            (self.tenant_id, movement_id),
        ).fetchall()
        return [dict(row) for row in rows]

    def _verify_stock(self, movement: Mapping[str, Any], *, direction: int) -> None:
        lines = self._stock_lines(str(movement["id"]))
        effects: dict[tuple[str, str, str | None], int] = {}
        policies: dict[str, bool] = {}
        serials: dict[tuple[str, str], tuple[int, int]] = {}
        if not lines:
            raise PlatformError("Inventory movement requires at least one line.")
        for line in lines:
            lot_id = str(line["inventory_lot_id"]) if line["inventory_lot_id"] is not None else None
            quantity = int(line["quantity_scaled"]) * direction
            item_id = str(line["item_id"])
            for field, sign, policy in (
                ("from_location_id", -1, "from_allow_negative"),
                ("to_location_id", 1, "to_allow_negative"),
            ):
                if line[field] is not None:
                    location_id = str(line[field])
                    effect_key = (location_id, item_id, lot_id)
                    effects[effect_key] = effects.get(effect_key, 0) + sign * quantity
                    policies[location_id] = bool(line[policy])
            if line["tracking_mode"] == "Serial" and lot_id is not None:
                serial_key = (item_id, lot_id)
                current, precision = serials.get(serial_key, (0, int(line["quantity_precision"])))
                serials[serial_key] = (
                    current
                    + (quantity if line["to_location_id"] is not None else 0)
                    - (quantity if line["from_location_id"] is not None else 0),
                    precision,
                )
        lock_keys = [
            f"{movement['workspace_id']}|{movement['legal_entity_id']}|{location}|{item}|{lot or ''}"
            for location, item, lot in effects
        ]
        lock_keys += [
            f"{movement['workspace_id']}|{movement['legal_entity_id']}|SERIAL|{item}|{lot}" for item, lot in serials
        ]
        for lock_key in sorted(set(lock_keys)):
            self.connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (lock_key,))
        for (location, item, lot), effect in effects.items():
            row = self.connection.execute(
                """SELECT COALESCE(SUM(CASE WHEN l.to_location_id=%s THEN l.quantity_scaled ELSE 0 END-CASE WHEN l.from_location_id=%s THEN l.quantity_scaled ELSE 0 END),0) quantity FROM reconforge.inventory_movement_lines l JOIN reconforge.inventory_movements m ON m.tenant_id=l.tenant_id AND m.id=l.movement_id WHERE l.tenant_id=%s AND m.workspace_id=%s AND m.organization_id=%s AND m.legal_entity_id=%s AND m.status='Posted' AND l.item_id=%s AND l.inventory_lot_id IS NOT DISTINCT FROM %s AND (l.to_location_id=%s OR l.from_location_id=%s)""",
                (
                    location,
                    location,
                    self.tenant_id,
                    movement["workspace_id"],
                    movement["organization_id"],
                    movement["legal_entity_id"],
                    item,
                    lot,
                    location,
                    location,
                ),
            ).fetchone()
            current = int(row["quantity"])
            if current + effect < 0 and not policies.get(location, False):
                raise PlatformError("Inventory movement would create negative stock in a protected location.")
        for (item, lot), (effect, precision) in serials.items():
            row = self.connection.execute(
                """SELECT COALESCE(SUM(CASE WHEN l.to_location_id IS NOT NULL THEN l.quantity_scaled ELSE 0 END-CASE WHEN l.from_location_id IS NOT NULL THEN l.quantity_scaled ELSE 0 END),0) quantity FROM reconforge.inventory_movement_lines l JOIN reconforge.inventory_movements m ON m.tenant_id=l.tenant_id AND m.id=l.movement_id WHERE l.tenant_id=%s AND m.workspace_id=%s AND m.organization_id=%s AND m.legal_entity_id=%s AND m.status='Posted' AND l.item_id=%s AND l.inventory_lot_id=%s""",
                (
                    self.tenant_id,
                    movement["workspace_id"],
                    movement["organization_id"],
                    movement["legal_entity_id"],
                    item,
                    lot,
                ),
            ).fetchone()
            if int(row["quantity"]) + effect not in (0, 10**precision):
                raise PlatformError("Serial tracking permits exactly zero or one on-hand unit per serial number.")

    def post_movement(self, movement_id: str, *, reason: str, actor_label: str = "local-cli") -> dict[str, Any]:
        actor = clean_text(actor_label, "Actor label")
        post_reason = clean_text(reason, "Posting reason", maximum=500)
        with self._transaction():
            movement = self._get_movement(movement_id, lock=True)
            if movement["status"] != "Draft":
                raise PlatformError("Only Draft inventory movements can be posted.")
            if same_actor(movement["created_by"], actor):
                raise PlatformError("Segregation of duties prevents posting your own inventory movement.")
            period = self._period(str(movement["workspace_id"]), str(movement["period_id"]))
            moved_on = iso_date(movement["movement_date"], "Movement date")
            start = iso_date(period["start_date"], "Stored period start date")
            end = iso_date(period["end_date"], "Stored period end date")
            if (
                period["status"] != "Open"
                or moved_on is None
                or start is None
                or end is None
                or not start <= moved_on <= end
            ):
                raise PlatformError("Inventory movements require an Open fiscal period containing the movement date.")
            self._verify_stock(movement, direction=1)
            row = self.connection.execute(
                "UPDATE reconforge.inventory_movements SET status='Posted',posted_by=%s,posted_at=now(),post_reason=%s,updated_at=now(),row_version=row_version+1 WHERE tenant_id=%s AND id=%s AND status='Draft' RETURNING row_version",
                (actor, post_reason, self.tenant_id, movement_id),
            ).fetchone()
            if row is None:
                raise PlatformError("Inventory movement changed concurrently; reload and retry.")
            self._event(
                actor_label=actor,
                object_type="inventory_movement",
                object_id=movement_id,
                action="inventory_movement_posted",
                version=row["row_version"],
                metadata={"movement_number": movement["movement_number"], "reason": post_reason},
            )
            return self._get_movement(movement_id)

    def void_movement(self, movement_id: str, *, reason: str, actor_label: str = "local-cli") -> dict[str, Any]:
        actor = clean_text(actor_label, "Actor label")
        void_reason = clean_text(reason, "Void reason", maximum=500)
        with self._transaction():
            movement = self._get_movement(movement_id, lock=True)
            if movement["status"] != "Posted":
                raise PlatformError("Only Posted inventory movements can be voided.")
            valuation_table = self.connection.execute(
                "SELECT to_regclass('reconforge.inventory_valuation_documents')"
            ).fetchone()
            valuation_table_name = (
                next(iter(valuation_table.values())) if isinstance(valuation_table, Mapping) else valuation_table[0]
            )
            if valuation_table_name is not None:
                valuation = self.connection.execute(
                    "SELECT valuation_number FROM reconforge.inventory_valuation_documents WHERE tenant_id=%s AND movement_id=%s AND status='Approved' LIMIT 1",
                    (self.tenant_id, movement_id),
                ).fetchone()
                if valuation is not None:
                    raise PlatformError(
                        f"Approved inventory valuation {valuation['valuation_number']} must be reversed before voiding its movement."
                    )
            reversal_table = self.connection.execute(
                "SELECT to_regclass('reconforge.inventory_valuation_reversals')"
            ).fetchone()
            reversal_table_name = (
                next(iter(reversal_table.values())) if isinstance(reversal_table, Mapping) else reversal_table[0]
            )
            if reversal_table_name is not None:
                reversal = self.connection.execute(
                    "SELECT reversal_number FROM reconforge.inventory_valuation_reversals WHERE tenant_id=%s AND reversal_movement_id=%s AND status='Approved' LIMIT 1",
                    (self.tenant_id, movement_id),
                ).fetchone()
                if reversal is not None:
                    raise PlatformError(
                        f"Approved valuation reversal {reversal['reversal_number']} protects its compensating movement."
                    )
            period = self._period(str(movement["workspace_id"]), str(movement["period_id"]))
            if period["status"] != "Open":
                raise PlatformError("Posted inventory movements can be voided only while their fiscal period is Open.")
            self._verify_stock(movement, direction=-1)
            row = self.connection.execute(
                "UPDATE reconforge.inventory_movements SET status='Voided',voided_by=%s,voided_at=now(),void_reason=%s,updated_at=now(),row_version=row_version+1 WHERE tenant_id=%s AND id=%s AND status='Posted' RETURNING row_version",
                (actor, void_reason, self.tenant_id, movement_id),
            ).fetchone()
            if row is None:
                raise PlatformError("Inventory movement changed concurrently; reload and retry.")
            self._event(
                actor_label=actor,
                object_type="inventory_movement",
                object_id=movement_id,
                action="inventory_movement_voided",
                version=row["row_version"],
                metadata={"movement_number": movement["movement_number"], "reason": void_reason},
            )
            return self._get_movement(movement_id)

    def list_movements(
        self,
        *,
        workspace: str = "default",
        organization_code: str = "",
        entity_code: str = "",
        period_id: str = "",
        status: str = "",
        limit: int = 500,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]:
        limit, offset = page(limit, offset)
        with self._transaction():
            workspace_id = self._workspace_id(workspace)
            sql = """SELECT m.*,o.organization_code,e.entity_code,p.name period_name,(SELECT COUNT(*) FROM reconforge.inventory_movement_lines l WHERE l.tenant_id=m.tenant_id AND l.movement_id=m.id) line_count FROM reconforge.inventory_movements m JOIN reconforge.organizations o ON o.tenant_id=m.tenant_id AND o.id=m.organization_id JOIN reconforge.legal_entities e ON e.tenant_id=m.tenant_id AND e.id=m.legal_entity_id JOIN reconforge.fiscal_periods p ON p.tenant_id=m.tenant_id AND p.id=m.period_id WHERE m.tenant_id=%s AND m.workspace_id=%s"""
            params: list[object] = [self.tenant_id, workspace_id]
            organization = None
            if organization_code.strip():
                organization = self._organization(workspace_id, organization_code)
                sql += " AND m.organization_id=%s"
                params.append(organization["id"])
            if entity_code.strip():
                if organization is None:
                    raise PlatformError("Organization is required when filtering by legal entity.")
                entity = self._entity(str(organization["id"]), entity_code)
                sql += " AND m.legal_entity_id=%s"
                params.append(entity["id"] if entity else "")
            if period_id.strip():
                sql += " AND m.period_id=%s"
                params.append(clean_text(period_id, "Period identifier"))
            if status.strip():
                sql += " AND m.status=%s"
                params.append(choice(status, "Movement status", ("Draft", "Posted", "Voided")))
            sql += " ORDER BY m.movement_date DESC,m.movement_number,m.id LIMIT %s OFFSET %s"
            params.extend((limit, offset))
            return [public_record(row) for row in self.connection.execute(sql, tuple(params)).fetchall()]
