"""Governed local inventory masters, movements, balances, and control exceptions."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any

from reconforge.domain.models import utc_now_text
from reconforge.platform.common import (
    PlatformError,
    audit,
    ensure_platform_schema,
    ensure_workspace,
    platform_id,
    require_permission,
)
from reconforge.platform.inventory_values import (
    DEFAULT_LIST_LIMIT,
    MAX_LIST_LIMIT,
)
from reconforge.platform.inventory_values import (
    choice as _choice,
)
from reconforge.platform.inventory_values import (
    clean_text as _clean_text,
)
from reconforge.platform.inventory_values import (
    code as _code,
)
from reconforge.platform.inventory_values import (
    iso_date as _iso_date,
)
from reconforge.platform.inventory_values import (
    movement_number as _movement_number,
)
from reconforge.platform.inventory_values import (
    page as _page,
)
from reconforge.platform.inventory_values import (
    public_record as _public_record,
)
from reconforge.platform.inventory_values import (
    quantity_to_scaled as _quantity_to_scaled,
)
from reconforge.platform.inventory_values import (
    scaled_to_text as _scaled_to_text,
)
from reconforge.utils.time import utc_today

INVENTORY_READ_PERMISSION = "inventory.read"
INVENTORY_MANAGE_PERMISSION = "inventory.manage"
INVENTORY_POST_PERMISSION = "inventory.post"
UOM_CATEGORIES = ("Count", "Weight", "Volume", "Length", "Time", "Custom")
ITEM_TYPES = ("Stock", "Consumable", "Service")
TRACKING_MODES = ("None", "Lot", "Serial")
LOCATION_TYPES = ("Internal", "Transit", "Supplier", "Customer", "Adjustment")
MOVEMENT_TYPES = ("Receipt", "Delivery", "Transfer", "Adjustment")
MOVEMENT_SOURCE_TYPES = ("Manual", "Imported", "Generated")
MOVEMENT_STATUSES = ("Draft", "Posted", "Voided")
MAX_MOVEMENT_LINES = 1_000


@dataclass(frozen=True)
class InventoryCoreSummary:
    """Counts for one workspace's local inventory-control records."""

    workspace: str
    units_of_measure: int
    items: int
    warehouses: int
    locations: int
    lots_and_serials: int
    draft_movements: int
    posted_movements: int
    voided_movements: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class InventoryCoreService:
    """Manage exact local inventory-control state without source-ERP writeback."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        ensure_platform_schema(connection)
        self.connection = connection
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        expected = {
            "units_of_measure",
            "inventory_items",
            "warehouses",
            "inventory_locations",
            "inventory_lots",
            "inventory_movements",
            "inventory_movement_lines",
        }
        try:
            existing = {
                str(row["name"])
                for row in self.connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
            }
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to inspect the local inventory-core schema.") from exc
        if not expected <= existing:
            raise PlatformError("Inventory-core schema is not initialized. Run 'reconforge db migrate' first.")

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
        require_permission(self.connection, actor_label=actor_label, permission=INVENTORY_MANAGE_PERMISSION)
        workspace_id = ensure_workspace(self.connection, _clean_text(workspace, "Workspace name"))
        code = _code(uom_code, "Unit code")
        if not 0 <= decimal_places <= 6:
            raise PlatformError("Unit decimal places must be between 0 and 6.")
        selected_category = _choice(category, "Unit category", UOM_CATEGORIES)
        uom_id = f"UOM-{workspace_id}" if code == "EA" else platform_id("UOM", workspace_id, code)
        existing = self.connection.execute(
            "SELECT id, category, decimal_places FROM units_of_measure WHERE workspace_id = ? AND uom_code = ?",
            (workspace_id, code),
        ).fetchone()
        if existing is not None and (
            str(existing["category"]) != selected_category or int(existing["decimal_places"]) != decimal_places
        ):
            referenced = self.connection.execute(
                "SELECT 1 FROM inventory_items WHERE uom_id = ? LIMIT 1", (existing["id"],)
            ).fetchone()
            if referenced is not None:
                raise PlatformError("A unit referenced by inventory items cannot change category or precision.")
        if not active:
            referenced = self.connection.execute(
                "SELECT 1 FROM inventory_items WHERE uom_id = ? AND active = 1 LIMIT 1", (uom_id,)
            ).fetchone()
            if referenced is not None:
                raise PlatformError("Deactivate inventory items before deactivating their unit.")
        now = utc_now_text()
        try:
            self.connection.execute(
                """
                INSERT INTO units_of_measure (
                    id, workspace_id, uom_code, name, category, decimal_places, active, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(workspace_id, uom_code) DO UPDATE SET
                    name = excluded.name, category = excluded.category,
                    decimal_places = excluded.decimal_places, active = excluded.active,
                    updated_at = excluded.updated_at
                """,
                (
                    uom_id,
                    workspace_id,
                    code,
                    _clean_text(name, "Unit name"),
                    selected_category,
                    decimal_places,
                    int(active),
                    now,
                    now,
                ),
            )
            self.connection.commit()
        except sqlite3.DatabaseError as exc:
            self.connection.rollback()
            raise PlatformError("Unable to save the local unit of measure.") from exc
        record = self._uom(workspace_id, code)
        audit(
            self.connection,
            actor_label=actor_label,
            object_type="unit_of_measure",
            object_id=str(record["id"]),
            action="unit_of_measure_upserted",
            metadata={"uom_code": code, "decimal_places": decimal_places, "active": active},
        )
        return record

    def list_uoms(
        self,
        *,
        workspace: str = "default",
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]:
        require_permission(self.connection, actor_label=actor_label, permission=INVENTORY_READ_PERMISSION)
        page_limit, page_offset = _page(limit, offset)
        workspace_id = self._workspace_id(workspace)
        if workspace_id is None:
            return []
        try:
            rows = self.connection.execute(
                "SELECT * FROM units_of_measure WHERE workspace_id = ? ORDER BY uom_code LIMIT ? OFFSET ?",
                (workspace_id, page_limit, page_offset),
            ).fetchall()
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to list local units of measure.") from exc
        return [_public_record(row) for row in rows]

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
        require_permission(self.connection, actor_label=actor_label, permission=INVENTORY_MANAGE_PERMISSION)
        workspace_id = ensure_workspace(self.connection, _clean_text(workspace, "Workspace name"))
        code = _code(item_code, "Item code")
        organization_id: str | None = None
        normalized_org = ""
        if organization_code.strip():
            organization = self._organization(workspace_id, _code(organization_code, "Organization code"))
            if not organization["active"]:
                raise PlatformError("Inventory items require an active organization when scoped.")
            organization_id = str(organization["id"])
            normalized_org = str(organization["organization_code"])
        uom = self._uom(workspace_id, _code(uom_code, "Unit code"))
        if not uom["active"]:
            raise PlatformError("Inventory items require an active unit of measure.")
        selected_type = _choice(item_type, "Item type", ITEM_TYPES)
        selected_tracking = _choice(tracking_mode, "Tracking mode", TRACKING_MODES)
        if selected_type == "Service" and selected_tracking != "None":
            raise PlatformError("Service items cannot use lot or serial tracking.")
        account_id: str | None = None
        account_code = ""
        if inventory_account_code.strip():
            account = self._account(workspace_id, _code(inventory_account_code, "Inventory account code"))
            if not account["active"]:
                raise PlatformError("Inventory account reference must be active.")
            chart_org = account["chart_organization_id"]
            if organization_id is not None and chart_org is not None and str(chart_org) != organization_id:
                raise PlatformError("Inventory account chart belongs to a different organization.")
            account_id = str(account["id"])
            account_code = str(account["account_code"])
        item_id = platform_id("ITEM", workspace_id, code)
        existing = self.connection.execute(
            """
            SELECT id, organization_id, uom_id, item_type, tracking_mode
            FROM inventory_items WHERE workspace_id = ? AND item_code = ?
            """,
            (workspace_id, code),
        ).fetchone()
        if existing is not None and (
            existing["organization_id"] != organization_id
            or str(existing["uom_id"]) != str(uom["id"])
            or str(existing["item_type"]) != selected_type
            or str(existing["tracking_mode"]) != selected_tracking
        ):
            referenced = self.connection.execute(
                "SELECT 1 FROM inventory_movement_lines WHERE item_id = ? LIMIT 1", (existing["id"],)
            ).fetchone()
            if referenced is not None:
                raise PlatformError("A referenced inventory item cannot change scope, unit, type, or tracking mode.")
        if not active:
            referenced = self.connection.execute(
                "SELECT 1 FROM inventory_movement_lines WHERE item_id = ? LIMIT 1", (item_id,)
            ).fetchone()
            if referenced is not None:
                raise PlatformError("Items referenced by inventory movements cannot be deactivated.")
        now = utc_now_text()
        try:
            self.connection.execute(
                """
                INSERT INTO inventory_items (
                    id, workspace_id, organization_id, item_code, name, item_type, tracking_mode,
                    uom_id, inventory_account_id, description, active, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(workspace_id, item_code) DO UPDATE SET
                    organization_id = excluded.organization_id, name = excluded.name,
                    item_type = excluded.item_type, tracking_mode = excluded.tracking_mode,
                    uom_id = excluded.uom_id, inventory_account_id = excluded.inventory_account_id,
                    description = excluded.description, active = excluded.active,
                    updated_at = excluded.updated_at
                """,
                (
                    item_id,
                    workspace_id,
                    organization_id,
                    code,
                    _clean_text(name, "Item name"),
                    selected_type,
                    selected_tracking,
                    uom["id"],
                    account_id,
                    _clean_text(description, "Item description", maximum=500, required=False),
                    int(active),
                    now,
                    now,
                ),
            )
            self.connection.commit()
        except sqlite3.DatabaseError as exc:
            self.connection.rollback()
            raise PlatformError("Unable to save the local inventory item.") from exc
        record = self._item(workspace_id, code)
        audit(
            self.connection,
            actor_label=actor_label,
            object_type="inventory_item",
            object_id=str(record["id"]),
            action="inventory_item_upserted",
            metadata={
                "item_code": code,
                "organization_code": normalized_org,
                "uom_code": uom["uom_code"],
                "inventory_account_code": account_code,
                "active": active,
            },
        )
        return record

    def list_items(
        self,
        *,
        workspace: str = "default",
        organization_code: str = "",
        active_only: bool = False,
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]:
        require_permission(self.connection, actor_label=actor_label, permission=INVENTORY_READ_PERMISSION)
        page_limit, page_offset = _page(limit, offset)
        workspace_id = self._workspace_id(workspace)
        if workspace_id is None:
            return []
        query = """
            SELECT items.*, organizations.organization_code, units.uom_code, units.decimal_places,
                   accounts.account_code AS inventory_account_code
            FROM inventory_items items
            LEFT JOIN organizations ON organizations.id = items.organization_id
            JOIN units_of_measure units ON units.id = items.uom_id
            LEFT JOIN accounts ON accounts.id = items.inventory_account_id
            WHERE items.workspace_id = ?
        """
        parameters: list[object] = [workspace_id]
        if organization_code:
            query += " AND organizations.organization_code = ?"
            parameters.append(_code(organization_code, "Organization code"))
        if active_only:
            query += " AND items.active = 1"
        query += " ORDER BY items.item_code LIMIT ? OFFSET ?"
        parameters.extend((page_limit, page_offset))
        try:
            rows = self.connection.execute(query, parameters).fetchall()
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to list local inventory items.") from exc
        return [_public_record(row) for row in rows]

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
        require_permission(self.connection, actor_label=actor_label, permission=INVENTORY_MANAGE_PERMISSION)
        workspace_id = ensure_workspace(self.connection, _clean_text(workspace, "Workspace name"))
        organization = self._organization(workspace_id, _code(organization_code, "Organization code"))
        if not organization["active"]:
            raise PlatformError("Warehouses require an active organization.")
        entity_id: str | None = None
        normalized_entity = ""
        if entity_code.strip():
            entity = self._entity(str(organization["id"]), _code(entity_code, "Entity code"))
            if not entity["active"]:
                raise PlatformError("Warehouses require an active legal entity when scoped.")
            entity_id = str(entity["id"])
            normalized_entity = str(entity["entity_code"])
        code = _code(warehouse_code, "Warehouse code")
        warehouse_id = platform_id("WH", workspace_id, organization["id"], code)
        existing = self.connection.execute(
            """
            SELECT id, legal_entity_id FROM warehouses
            WHERE workspace_id = ? AND organization_id = ? AND warehouse_code = ?
            """,
            (workspace_id, organization["id"], code),
        ).fetchone()
        if existing is not None and existing["legal_entity_id"] != entity_id:
            referenced = self.connection.execute(
                """
                SELECT 1 FROM inventory_movement_lines lines
                JOIN inventory_locations locations
                  ON locations.id IN (lines.from_location_id, lines.to_location_id)
                WHERE locations.warehouse_id = ? LIMIT 1
                """,
                (existing["id"],),
            ).fetchone()
            if referenced is not None:
                raise PlatformError("A referenced warehouse cannot change legal-entity scope.")
        if not active:
            referenced = self.connection.execute(
                "SELECT 1 FROM inventory_locations WHERE warehouse_id = ? AND active = 1 LIMIT 1",
                (warehouse_id,),
            ).fetchone()
            if referenced is not None:
                raise PlatformError("Deactivate warehouse locations before deactivating their warehouse.")
        now = utc_now_text()
        try:
            self.connection.execute(
                """
                INSERT INTO warehouses (
                    id, workspace_id, organization_id, legal_entity_id, warehouse_code,
                    name, active, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(workspace_id, organization_id, warehouse_code) DO UPDATE SET
                    legal_entity_id = excluded.legal_entity_id, name = excluded.name,
                    active = excluded.active, updated_at = excluded.updated_at
                """,
                (
                    warehouse_id,
                    workspace_id,
                    organization["id"],
                    entity_id,
                    code,
                    _clean_text(name, "Warehouse name"),
                    int(active),
                    now,
                    now,
                ),
            )
            self.connection.commit()
        except sqlite3.DatabaseError as exc:
            self.connection.rollback()
            raise PlatformError("Unable to save the local warehouse.") from exc
        record = self._warehouse(workspace_id, str(organization["id"]), code)
        audit(
            self.connection,
            actor_label=actor_label,
            object_type="warehouse",
            object_id=str(record["id"]),
            action="warehouse_upserted",
            metadata={
                "warehouse_code": code,
                "organization_code": organization["organization_code"],
                "entity_code": normalized_entity,
                "active": active,
            },
        )
        return record

    def list_warehouses(
        self,
        *,
        workspace: str = "default",
        organization_code: str = "",
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]:
        require_permission(self.connection, actor_label=actor_label, permission=INVENTORY_READ_PERMISSION)
        page_limit, page_offset = _page(limit, offset)
        workspace_id = self._workspace_id(workspace)
        if workspace_id is None:
            return []
        query = """
            SELECT warehouses.*, organizations.organization_code, legal_entities.entity_code
            FROM warehouses
            JOIN organizations ON organizations.id = warehouses.organization_id
            LEFT JOIN legal_entities ON legal_entities.id = warehouses.legal_entity_id
            WHERE warehouses.workspace_id = ?
        """
        parameters: list[object] = [workspace_id]
        if organization_code:
            query += " AND organizations.organization_code = ?"
            parameters.append(_code(organization_code, "Organization code"))
        query += " ORDER BY organizations.organization_code, warehouses.warehouse_code LIMIT ? OFFSET ?"
        parameters.extend((page_limit, page_offset))
        try:
            rows = self.connection.execute(query, parameters).fetchall()
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to list local warehouses.") from exc
        return [_public_record(row) for row in rows]

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
        require_permission(self.connection, actor_label=actor_label, permission=INVENTORY_MANAGE_PERMISSION)
        workspace_id = ensure_workspace(self.connection, _clean_text(workspace, "Workspace name"))
        organization = self._organization(workspace_id, _code(organization_code, "Organization code"))
        warehouse = self._warehouse(workspace_id, str(organization["id"]), _code(warehouse_code, "Warehouse code"))
        if not warehouse["active"]:
            raise PlatformError("Inventory locations require an active warehouse.")
        code = _code(location_code, "Location code")
        location_id = platform_id("LOC", warehouse["id"], code)
        existing = self.connection.execute(
            "SELECT id FROM inventory_locations WHERE warehouse_id = ? AND location_code = ?",
            (warehouse["id"], code),
        ).fetchone()
        if existing is not None:
            location_id = str(existing["id"])
        parent_id: str | None = None
        if parent_location_code.strip():
            parent = self._location(str(warehouse["id"]), _code(parent_location_code, "Parent location code"))
            parent_id = str(parent["id"])
            if parent_id == location_id:
                raise PlatformError("An inventory location cannot be its own parent.")
            if existing is not None and self._location_is_descendant(location_id, parent_id):
                raise PlatformError("Inventory location hierarchy must remain acyclic.")
        if not active:
            referenced = self.connection.execute(
                """
                SELECT 1 FROM inventory_movement_lines
                WHERE from_location_id = ? OR to_location_id = ? LIMIT 1
                """,
                (location_id, location_id),
            ).fetchone()
            if referenced is not None:
                raise PlatformError("Locations referenced by inventory movements cannot be deactivated.")
        if not allow_negative and existing is not None:
            negative = self.connection.execute(
                """
                SELECT 1 FROM (
                    SELECT lines.item_id, lines.inventory_lot_id,
                           SUM(CASE WHEN lines.to_location_id = ? THEN lines.quantity_scaled ELSE 0 END) -
                           SUM(CASE WHEN lines.from_location_id = ? THEN lines.quantity_scaled ELSE 0 END) AS balance
                    FROM inventory_movement_lines lines
                    JOIN inventory_movements movements ON movements.id = lines.movement_id
                    WHERE movements.status = 'Posted'
                      AND (lines.to_location_id = ? OR lines.from_location_id = ?)
                    GROUP BY lines.item_id, lines.inventory_lot_id
                ) balances WHERE balance < 0 LIMIT 1
                """,
                (location_id, location_id, location_id, location_id),
            ).fetchone()
            if negative is not None:
                raise PlatformError("This location currently has negative stock and cannot disallow it.")
        now = utc_now_text()
        try:
            self.connection.execute(
                """
                INSERT INTO inventory_locations (
                    id, warehouse_id, parent_location_id, location_code, name, location_type,
                    allow_negative, active, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(warehouse_id, location_code) DO UPDATE SET
                    parent_location_id = excluded.parent_location_id, name = excluded.name,
                    location_type = excluded.location_type, allow_negative = excluded.allow_negative,
                    active = excluded.active, updated_at = excluded.updated_at
                """,
                (
                    location_id,
                    warehouse["id"],
                    parent_id,
                    code,
                    _clean_text(name, "Location name"),
                    _choice(location_type, "Location type", LOCATION_TYPES),
                    int(allow_negative),
                    int(active),
                    now,
                    now,
                ),
            )
            self.connection.commit()
        except sqlite3.DatabaseError as exc:
            self.connection.rollback()
            raise PlatformError("Unable to save the local inventory location.") from exc
        record = self._location(str(warehouse["id"]), code)
        audit(
            self.connection,
            actor_label=actor_label,
            object_type="inventory_location",
            object_id=str(record["id"]),
            action="inventory_location_upserted",
            metadata={
                "warehouse_code": warehouse["warehouse_code"],
                "location_code": code,
                "allow_negative": allow_negative,
                "active": active,
            },
        )
        return record

    def list_locations(
        self,
        *,
        workspace: str = "default",
        organization_code: str = "",
        warehouse_code: str = "",
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]:
        require_permission(self.connection, actor_label=actor_label, permission=INVENTORY_READ_PERMISSION)
        page_limit, page_offset = _page(limit, offset)
        workspace_id = self._workspace_id(workspace)
        if workspace_id is None:
            return []
        query = """
            SELECT locations.*, warehouses.warehouse_code, organizations.organization_code,
                   parents.location_code AS parent_location_code
            FROM inventory_locations locations
            JOIN warehouses ON warehouses.id = locations.warehouse_id
            JOIN organizations ON organizations.id = warehouses.organization_id
            LEFT JOIN inventory_locations parents ON parents.id = locations.parent_location_id
            WHERE warehouses.workspace_id = ?
        """
        parameters: list[object] = [workspace_id]
        if organization_code:
            query += " AND organizations.organization_code = ?"
            parameters.append(_code(organization_code, "Organization code"))
        if warehouse_code:
            query += " AND warehouses.warehouse_code = ?"
            parameters.append(_code(warehouse_code, "Warehouse code"))
        query += " ORDER BY organizations.organization_code, warehouses.warehouse_code, locations.location_code LIMIT ? OFFSET ?"
        parameters.extend((page_limit, page_offset))
        try:
            rows = self.connection.execute(query, parameters).fetchall()
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to list local inventory locations.") from exc
        return [_public_record(row) for row in rows]

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
        require_permission(self.connection, actor_label=actor_label, permission=INVENTORY_MANAGE_PERMISSION)
        workspace_id = ensure_workspace(self.connection, _clean_text(workspace, "Workspace name"))
        organization = self._organization(workspace_id, _code(organization_code, "Organization code"))
        item = self._item(workspace_id, _code(item_code, "Item code"))
        if item["organization_id"] is not None and str(item["organization_id"]) != str(organization["id"]):
            raise PlatformError("Tracked item belongs to a different organization.")
        tracking_type = str(item["tracking_mode"])
        if tracking_type not in {"Lot", "Serial"}:
            raise PlatformError("Lot/serial references require an item configured for Lot or Serial tracking.")
        if not item["active"]:
            raise PlatformError("Lot/serial references require an active inventory item.")
        lot_code = _code(lot_serial_code, "Lot/serial code")
        manufactured = _iso_date(manufactured_on, "Manufacture date", required=False)
        expires = _iso_date(expires_on, "Expiry date", required=False)
        if manufactured is not None and expires is not None and manufactured > expires:
            raise PlatformError("Expiry date cannot be earlier than manufacture date.")
        lot_id = platform_id("LOT", item["id"], organization["id"], lot_code)
        if not active:
            referenced = self.connection.execute(
                "SELECT 1 FROM inventory_movement_lines WHERE inventory_lot_id = ? LIMIT 1", (lot_id,)
            ).fetchone()
            if referenced is not None:
                raise PlatformError("Lots or serials referenced by inventory movements cannot be deactivated.")
        now = utc_now_text()
        try:
            self.connection.execute(
                """
                INSERT INTO inventory_lots (
                    id, workspace_id, organization_id, item_id, lot_serial_code, tracking_type,
                    manufactured_on, expires_on, active, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(item_id, organization_id, lot_serial_code) DO UPDATE SET
                    manufactured_on = excluded.manufactured_on, expires_on = excluded.expires_on,
                    active = excluded.active, updated_at = excluded.updated_at
                """,
                (
                    lot_id,
                    workspace_id,
                    organization["id"],
                    item["id"],
                    lot_code,
                    tracking_type,
                    manufactured.isoformat() if manufactured else None,
                    expires.isoformat() if expires else None,
                    int(active),
                    now,
                    now,
                ),
            )
            self.connection.commit()
        except sqlite3.DatabaseError as exc:
            self.connection.rollback()
            raise PlatformError("Unable to save the local lot or serial reference.") from exc
        record = self._lot(str(item["id"]), str(organization["id"]), lot_code)
        audit(
            self.connection,
            actor_label=actor_label,
            object_type="inventory_lot",
            object_id=str(record["id"]),
            action="inventory_lot_upserted",
            metadata={
                "item_code": item["item_code"],
                "lot_serial_code": lot_code,
                "tracking_type": tracking_type,
                "active": active,
            },
        )
        return record

    def list_lots(
        self,
        *,
        workspace: str = "default",
        organization_code: str = "",
        item_code: str = "",
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]:
        require_permission(self.connection, actor_label=actor_label, permission=INVENTORY_READ_PERMISSION)
        page_limit, page_offset = _page(limit, offset)
        workspace_id = self._workspace_id(workspace)
        if workspace_id is None:
            return []
        query = """
            SELECT lots.*, items.item_code, organizations.organization_code
            FROM inventory_lots lots
            JOIN inventory_items items ON items.id = lots.item_id
            JOIN organizations ON organizations.id = lots.organization_id
            WHERE lots.workspace_id = ?
        """
        parameters: list[object] = [workspace_id]
        if organization_code:
            query += " AND organizations.organization_code = ?"
            parameters.append(_code(organization_code, "Organization code"))
        if item_code:
            query += " AND items.item_code = ?"
            parameters.append(_code(item_code, "Item code"))
        query += " ORDER BY items.item_code, lots.lot_serial_code LIMIT ? OFFSET ?"
        parameters.extend((page_limit, page_offset))
        try:
            rows = self.connection.execute(query, parameters).fetchall()
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to list local lots and serials.") from exc
        return [_public_record(row) for row in rows]

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
        """Create or replace one exact-quantity Draft movement."""

        require_permission(self.connection, actor_label=actor_label, permission=INVENTORY_MANAGE_PERMISSION)
        workspace_id = ensure_workspace(self.connection, _clean_text(workspace, "Workspace name"))
        organization = self._organization(workspace_id, _code(organization_code, "Organization code"))
        if not organization["active"]:
            raise PlatformError("Inventory movements require an active organization.")
        entity = self._entity(str(organization["id"]), _code(entity_code, "Entity code"))
        if not entity["active"]:
            raise PlatformError("Inventory movements require an active legal entity.")
        period = self._period(period_id, workspace_id)
        moved_on = _iso_date(movement_date, "Movement date")
        if moved_on is None:
            raise PlatformError("Movement date is required.")
        self._require_open_period_date(period, moved_on)
        selected_type = _choice(movement_type, "Movement type", MOVEMENT_TYPES)
        selected_source = _choice(source_type, "Movement source type", MOVEMENT_SOURCE_TYPES)
        number = _movement_number(movement_number)
        creator = _clean_text(actor_label or "local-cli", "Actor label")
        if not 1 <= len(lines) <= MAX_MOVEMENT_LINES:
            raise PlatformError(f"Inventory movements require between 1 and {MAX_MOVEMENT_LINES} lines.")
        prepared: list[dict[str, Any]] = []
        serials_seen: set[str] = set()
        for line_number, line in enumerate(lines, start=1):
            if not isinstance(line, Mapping):
                raise PlatformError("Each inventory movement line must be an object.")
            item = self._item(workspace_id, _code(line.get("item_code"), "Item code"))
            if not item["active"] or item["item_type"] == "Service":
                raise PlatformError("Movement lines require an active stock or consumable item.")
            if item["organization_id"] is not None and str(item["organization_id"]) != str(organization["id"]):
                raise PlatformError("Movement item belongs to a different organization.")
            quantity_scaled = _quantity_to_scaled(line.get("quantity"), int(item["decimal_places"]), "Line quantity")
            from_location = self._optional_location_reference(
                workspace_id, str(organization["id"]), str(entity["id"]), line.get("from_location")
            )
            to_location = self._optional_location_reference(
                workspace_id, str(organization["id"]), str(entity["id"]), line.get("to_location")
            )
            self._validate_line_direction(selected_type, from_location, to_location)
            lot: dict[str, Any] | None = None
            lot_code = _clean_text(line.get("lot_serial_code", ""), "Lot/serial code", maximum=64, required=False)
            tracking_mode = str(item["tracking_mode"])
            if tracking_mode == "None" and lot_code:
                raise PlatformError("Untracked items cannot carry a lot or serial reference.")
            if tracking_mode != "None":
                if not lot_code:
                    raise PlatformError("Tracked movement items require a lot or serial reference.")
                lot = self._lot(str(item["id"]), str(organization["id"]), _code(lot_code, "Lot/serial code"))
                if not lot["active"] or str(lot["tracking_type"]) != tracking_mode:
                    raise PlatformError(
                        "Movement line requires an active lot/serial matching the item's tracking mode."
                    )
                if tracking_mode == "Serial":
                    if quantity_scaled != 10 ** int(item["decimal_places"]):
                        raise PlatformError("A serial-tracked movement line must contain exactly one unit.")
                    serial_key = str(lot["id"])
                    if serial_key in serials_seen:
                        raise PlatformError("A serial number can appear only once in one inventory movement.")
                    serials_seen.add(serial_key)
            prepared.append(
                {
                    "line_number": line_number,
                    "item_id": item["id"],
                    "uom_id": item["uom_id"],
                    "inventory_lot_id": lot["id"] if lot else None,
                    "from_location_id": from_location["id"] if from_location else None,
                    "to_location_id": to_location["id"] if to_location else None,
                    "quantity_scaled": quantity_scaled,
                    "quantity_precision": int(item["decimal_places"]),
                    "description": _clean_text(
                        line.get("description", ""), "Line description", maximum=500, required=False
                    ),
                }
            )
        movement_id = platform_id("MOV", workspace_id, number)
        now = utc_now_text()
        existing = self.connection.execute(
            "SELECT status, created_by, created_at FROM inventory_movements WHERE id = ?", (movement_id,)
        ).fetchone()
        if existing is not None and str(existing["status"]) != "Draft":
            raise PlatformError("Only Draft inventory movements can be replaced.")
        original_creator = str(existing["created_by"]) if existing is not None else creator
        original_created_at = str(existing["created_at"]) if existing is not None else now
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            if existing is not None:
                self.connection.execute("DELETE FROM inventory_movement_lines WHERE movement_id = ?", (movement_id,))
            self.connection.execute(
                """
                INSERT INTO inventory_movements (
                    id, workspace_id, organization_id, legal_entity_id, period_id,
                    movement_number, movement_type, movement_date, source_reference,
                    description, source_type, status, created_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Draft', ?, ?, ?)
                ON CONFLICT(workspace_id, movement_number) DO UPDATE SET
                    organization_id = excluded.organization_id,
                    legal_entity_id = excluded.legal_entity_id,
                    period_id = excluded.period_id,
                    movement_type = excluded.movement_type,
                    movement_date = excluded.movement_date,
                    source_reference = excluded.source_reference,
                    description = excluded.description,
                    source_type = excluded.source_type,
                    updated_at = excluded.updated_at
                """,
                (
                    movement_id,
                    workspace_id,
                    organization["id"],
                    entity["id"],
                    period["id"],
                    number,
                    selected_type,
                    moved_on.isoformat(),
                    _clean_text(source_reference, "Source reference", maximum=160, required=False),
                    _clean_text(description, "Movement description", maximum=500),
                    selected_source,
                    original_creator,
                    original_created_at,
                    now,
                ),
            )
            for line in prepared:
                line_id = platform_id("MOVL", movement_id, line["line_number"])
                self.connection.execute(
                    """
                    INSERT INTO inventory_movement_lines (
                        id, movement_id, line_number, item_id, uom_id, inventory_lot_id,
                        from_location_id, to_location_id, quantity_scaled,
                        quantity_precision, description, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        line_id,
                        movement_id,
                        line["line_number"],
                        line["item_id"],
                        line["uom_id"],
                        line["inventory_lot_id"],
                        line["from_location_id"],
                        line["to_location_id"],
                        line["quantity_scaled"],
                        line["quantity_precision"],
                        line["description"],
                        now,
                    ),
                )
            stored = self.connection.execute(
                "SELECT * FROM inventory_movements WHERE id = ?", (movement_id,)
            ).fetchone()
            if stored is None:
                raise PlatformError("Unable to recheck the local inventory movement draft.")
            self._validate_movement_integrity(dict(stored), check_stock=False)
            self.connection.commit()
        except PlatformError:
            self.connection.rollback()
            raise
        except sqlite3.DatabaseError as exc:
            self.connection.rollback()
            raise PlatformError("Unable to save the local inventory movement.") from exc
        audit(
            self.connection,
            actor_label=actor_label,
            object_type="inventory_movement",
            object_id=movement_id,
            action="inventory_movement_draft_saved",
            metadata={"movement_number": number, "movement_type": selected_type, "line_count": len(prepared)},
        )
        return self.get_movement(movement_id, actor_label=actor_label)

    def post_movement(
        self,
        movement_id: str,
        *,
        reason: str,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        """Post a Draft into the local inventory ledger without updating a source ERP."""

        actor_user = require_permission(self.connection, actor_label=actor_label, permission=INVENTORY_POST_PERMISSION)
        post_reason = _clean_text(reason, "Posting reason", maximum=500)
        poster = _clean_text(actor_label or "local-cli", "Actor label")
        now = utc_now_text()
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            movement = self._movement(movement_id)
            if movement["status"] != "Draft":
                raise PlatformError("Only Draft inventory movements can be posted.")
            if actor_user is not None and str(movement["created_by"]) == actor_user.username:
                raise PlatformError("Segregation of duties prevents posting your own inventory movement.")
            self._validate_movement_integrity(movement, check_stock=True)
            cursor = self.connection.execute(
                """
                UPDATE inventory_movements
                SET status = 'Posted', posted_by = ?, posted_at = ?, post_reason = ?, updated_at = ?
                WHERE id = ? AND status = 'Draft'
                """,
                (poster, now, post_reason, now, movement_id),
            )
            if cursor.rowcount != 1:
                raise PlatformError("Inventory movement changed concurrently; reload and retry.")
            self.connection.commit()
        except PlatformError:
            self.connection.rollback()
            raise
        except sqlite3.DatabaseError as exc:
            self.connection.rollback()
            raise PlatformError("Unable to post the local inventory movement.") from exc
        audit(
            self.connection,
            actor_label=actor_label,
            object_type="inventory_movement",
            object_id=movement_id,
            action="inventory_movement_posted",
            metadata={"movement_number": movement["movement_number"], "reason": post_reason},
        )
        return self.get_movement(movement_id, actor_label=actor_label)

    def void_movement(
        self,
        movement_id: str,
        *,
        reason: str,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        """Void a Posted local movement when doing so preserves stock constraints."""

        require_permission(self.connection, actor_label=actor_label, permission=INVENTORY_POST_PERMISSION)
        void_reason = _clean_text(reason, "Void reason", maximum=500)
        actor = _clean_text(actor_label or "local-cli", "Actor label")
        now = utc_now_text()
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            movement = self._movement(movement_id)
            if movement["status"] != "Posted":
                raise PlatformError("Only Posted inventory movements can be voided.")
            valuation_table = self.connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'inventory_valuation_documents'"
            ).fetchone()
            approved_valuation = None
            if valuation_table is not None:
                approved_valuation = self.connection.execute(
                    """
                    SELECT valuation_number FROM inventory_valuation_documents
                    WHERE movement_id = ? AND status = 'Approved' LIMIT 1
                    """,
                    (movement_id,),
                ).fetchone()
            if approved_valuation is not None:
                raise PlatformError(
                    "Approved inventory valuation "
                    f"{approved_valuation['valuation_number']} must be reversed before voiding its movement."
                )
            reversal_table = self.connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'inventory_valuation_reversals'"
            ).fetchone()
            approved_reversal = None
            if reversal_table is not None:
                approved_reversal = self.connection.execute(
                    """
                    SELECT reversal_number FROM inventory_valuation_reversals
                    WHERE reversal_movement_id = ? AND status = 'Approved' LIMIT 1
                    """,
                    (movement_id,),
                ).fetchone()
            if approved_reversal is not None:
                raise PlatformError(
                    "Approved inventory valuation reversal "
                    f"{approved_reversal['reversal_number']} preserves this mirror movement as evidence."
                )
            period = self._period(str(movement["period_id"]), str(movement["workspace_id"]))
            if period["status"] != "Open":
                raise PlatformError("Posted inventory movements can be voided only while their fiscal period is Open.")
            lines = self._integrity_lines(movement)
            self._verify_projected_stock(movement, lines, direction=-1)
            cursor = self.connection.execute(
                """
                UPDATE inventory_movements
                SET status = 'Voided', voided_by = ?, voided_at = ?, void_reason = ?, updated_at = ?
                WHERE id = ? AND status = 'Posted'
                """,
                (actor, now, void_reason, now, movement_id),
            )
            if cursor.rowcount != 1:
                raise PlatformError("Inventory movement changed concurrently; reload and retry.")
            self.connection.commit()
        except PlatformError:
            self.connection.rollback()
            raise
        except sqlite3.DatabaseError as exc:
            self.connection.rollback()
            raise PlatformError("Unable to void the local inventory movement.") from exc
        audit(
            self.connection,
            actor_label=actor_label,
            object_type="inventory_movement",
            object_id=movement_id,
            action="inventory_movement_voided",
            metadata={"movement_number": movement["movement_number"], "reason": void_reason},
        )
        return self.get_movement(movement_id, actor_label=actor_label)

    def get_movement(self, movement_id: str, *, actor_label: str = "local-cli") -> dict[str, Any]:
        require_permission(self.connection, actor_label=actor_label, permission=INVENTORY_READ_PERMISSION)
        movement = self._movement(movement_id)
        try:
            rows = self.connection.execute(
                """
                SELECT lines.*, items.item_code, items.name AS item_name, units.uom_code,
                       lots.lot_serial_code,
                       from_warehouses.warehouse_code AS from_warehouse_code,
                       from_locations.location_code AS from_location_code,
                       to_warehouses.warehouse_code AS to_warehouse_code,
                       to_locations.location_code AS to_location_code
                FROM inventory_movement_lines lines
                JOIN inventory_items items ON items.id = lines.item_id
                JOIN units_of_measure units ON units.id = lines.uom_id
                LEFT JOIN inventory_lots lots ON lots.id = lines.inventory_lot_id
                LEFT JOIN inventory_locations from_locations ON from_locations.id = lines.from_location_id
                LEFT JOIN warehouses from_warehouses ON from_warehouses.id = from_locations.warehouse_id
                LEFT JOIN inventory_locations to_locations ON to_locations.id = lines.to_location_id
                LEFT JOIN warehouses to_warehouses ON to_warehouses.id = to_locations.warehouse_id
                WHERE lines.movement_id = ? ORDER BY lines.line_number
                """,
                (movement_id,),
            ).fetchall()
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to read local inventory movement lines.") from exc
        lines: list[dict[str, Any]] = []
        for row in rows:
            record = dict(row)
            record["quantity"] = _scaled_to_text(int(record["quantity_scaled"]), int(record["quantity_precision"]))
            record["from_location"] = self._location_label(
                record.pop("from_warehouse_code"), record.pop("from_location_code")
            )
            record["to_location"] = self._location_label(
                record.pop("to_warehouse_code"), record.pop("to_location_code")
            )
            lines.append(record)
        result = dict(movement)
        result["line_count"] = len(lines)
        result["lines"] = lines
        return result

    def list_movements(
        self,
        *,
        workspace: str = "default",
        organization_code: str = "",
        entity_code: str = "",
        period_id: str = "",
        status: str = "",
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]:
        require_permission(self.connection, actor_label=actor_label, permission=INVENTORY_READ_PERMISSION)
        page_limit, page_offset = _page(limit, offset)
        workspace_id = self._workspace_id(workspace)
        if workspace_id is None:
            return []
        query = """
            SELECT movements.*, organizations.organization_code, entities.entity_code,
                   periods.name AS period_name, COUNT(lines.id) AS line_count
            FROM inventory_movements movements
            JOIN organizations ON organizations.id = movements.organization_id
            JOIN legal_entities entities ON entities.id = movements.legal_entity_id
            JOIN periods ON periods.id = movements.period_id
            LEFT JOIN inventory_movement_lines lines ON lines.movement_id = movements.id
            WHERE movements.workspace_id = ?
        """
        parameters: list[object] = [workspace_id]
        if organization_code:
            query += " AND organizations.organization_code = ?"
            parameters.append(_code(organization_code, "Organization code"))
        if entity_code:
            query += " AND entities.entity_code = ?"
            parameters.append(_code(entity_code, "Entity code"))
        if period_id:
            query += " AND movements.period_id = ?"
            parameters.append(_clean_text(period_id, "Period identifier"))
        if status:
            query += " AND movements.status = ?"
            parameters.append(_choice(status, "Movement status", MOVEMENT_STATUSES))
        query += """
            GROUP BY movements.id
            ORDER BY movements.movement_date DESC, movements.movement_number
            LIMIT ? OFFSET ?
        """
        parameters.extend((page_limit, page_offset))
        try:
            return [dict(row) for row in self.connection.execute(query, parameters).fetchall()]
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to list local inventory movements.") from exc

    def on_hand(
        self,
        *,
        organization_code: str,
        entity_code: str,
        workspace: str = "default",
        item_code: str = "",
        warehouse_code: str = "",
        include_zero: bool = False,
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> dict[str, object]:
        """Return exact quantities derived only from Posted, non-Voided local movements."""

        require_permission(self.connection, actor_label=actor_label, permission=INVENTORY_READ_PERMISSION)
        page_limit, page_offset = _page(limit, offset)
        workspace_id = self._workspace_id(workspace)
        if workspace_id is None:
            raise PlatformError("Workspace reference was not found.")
        organization = self._organization(workspace_id, _code(organization_code, "Organization code"))
        entity = self._entity(str(organization["id"]), _code(entity_code, "Entity code"))
        query = """
            WITH stock AS (
                SELECT lines.to_location_id AS location_id, lines.item_id, lines.inventory_lot_id,
                       lines.uom_id, lines.quantity_precision, lines.quantity_scaled AS delta
                FROM inventory_movement_lines lines
                JOIN inventory_movements movements ON movements.id = lines.movement_id
                WHERE movements.workspace_id = ? AND movements.organization_id = ?
                  AND movements.legal_entity_id = ? AND movements.status = 'Posted'
                  AND lines.to_location_id IS NOT NULL
                UNION ALL
                SELECT lines.from_location_id AS location_id, lines.item_id, lines.inventory_lot_id,
                       lines.uom_id, lines.quantity_precision, -lines.quantity_scaled AS delta
                FROM inventory_movement_lines lines
                JOIN inventory_movements movements ON movements.id = lines.movement_id
                WHERE movements.workspace_id = ? AND movements.organization_id = ?
                  AND movements.legal_entity_id = ? AND movements.status = 'Posted'
                  AND lines.from_location_id IS NOT NULL
            )
            SELECT stock.location_id, warehouses.warehouse_code, locations.location_code,
                   locations.allow_negative, stock.item_id, items.item_code, items.name AS item_name,
                   units.uom_code, stock.inventory_lot_id, lots.lot_serial_code,
                   stock.quantity_precision, SUM(stock.delta) AS quantity_scaled
            FROM stock
            JOIN inventory_locations locations ON locations.id = stock.location_id
            JOIN warehouses ON warehouses.id = locations.warehouse_id
            JOIN inventory_items items ON items.id = stock.item_id
            JOIN units_of_measure units ON units.id = stock.uom_id
            LEFT JOIN inventory_lots lots ON lots.id = stock.inventory_lot_id
            WHERE 1 = 1
        """
        parameters: list[object] = [
            workspace_id,
            organization["id"],
            entity["id"],
            workspace_id,
            organization["id"],
            entity["id"],
        ]
        if item_code:
            query += " AND items.item_code = ?"
            parameters.append(_code(item_code, "Item code"))
        if warehouse_code:
            query += " AND warehouses.warehouse_code = ?"
            parameters.append(_code(warehouse_code, "Warehouse code"))
        query += """
            GROUP BY stock.location_id, warehouses.warehouse_code, locations.location_code,
                     locations.allow_negative, stock.item_id, items.item_code, items.name,
                     units.uom_code, stock.inventory_lot_id, lots.lot_serial_code,
                     stock.quantity_precision
        """
        if not include_zero:
            query += " HAVING SUM(stock.delta) <> 0"
        query += " ORDER BY warehouses.warehouse_code, locations.location_code, items.item_code, lots.lot_serial_code LIMIT ? OFFSET ?"
        parameters.extend((page_limit, page_offset))
        try:
            rows = self.connection.execute(query, parameters).fetchall()
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to compute local inventory on-hand quantities.") from exc
        records: list[dict[str, Any]] = []
        negative_count = 0
        for row in rows:
            record = _public_record(row)
            quantity_scaled = int(record["quantity_scaled"])
            precision = int(record["quantity_precision"])
            record["quantity"] = _scaled_to_text(quantity_scaled, precision)
            record["negative"] = quantity_scaled < 0
            negative_count += int(quantity_scaled < 0)
            records.append(record)
        return {
            "schema_version": 1,
            "source": {"kind": "local-inventory-ledger", "local_first": True, "external_calls": False},
            "workspace": _clean_text(workspace, "Workspace name"),
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
        """Derive deterministic local inventory-control exceptions without opaque scoring."""

        require_permission(self.connection, actor_label=actor_label, permission=INVENTORY_READ_PERMISSION)
        as_of_date = _iso_date(as_of, "As-of date", required=False) or utc_today()
        balances = self.on_hand(
            workspace=workspace,
            organization_code=organization_code,
            entity_code=entity_code,
            include_zero=False,
            limit=MAX_LIST_LIMIT,
            actor_label=actor_label,
        )
        exceptions: list[dict[str, object]] = []
        balance_rows = balances["balances"]
        if not isinstance(balance_rows, list):
            raise PlatformError("Unable to read local inventory balances for control evaluation.")
        try:
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
                lot_id = balance.get("inventory_lot_id")
                if lot_id:
                    lot = self.connection.execute(
                        "SELECT expires_on FROM inventory_lots WHERE id = ?", (lot_id,)
                    ).fetchone()
                    if lot is not None and lot["expires_on"] and str(lot["expires_on"]) < as_of_date.isoformat():
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
            if workspace_id is not None:
                organization = self._organization(workspace_id, _code(organization_code, "Organization code"))
                missing_accounts = self.connection.execute(
                    """
                    SELECT item_code FROM inventory_items
                    WHERE workspace_id = ? AND active = 1 AND item_type = 'Stock'
                      AND inventory_account_id IS NULL
                      AND (organization_id IS NULL OR organization_id = ?)
                    ORDER BY item_code
                    """,
                    (workspace_id, organization["id"]),
                ).fetchall()
                for item in missing_accounts:
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
        except sqlite3.Error as error:
            raise PlatformError("Unable to evaluate local inventory controls.") from error
        exceptions.sort(
            key=lambda item: (str(item["risk_rating"]), str(item["control_code"]), str(item["exception_id"]))
        )
        return {
            "schema_version": 1,
            "generated_at": utc_now_text(),
            "as_of": as_of_date.isoformat(),
            "source": {"kind": "local-inventory-controls", "local_first": True, "external_calls": False},
            "workspace": _clean_text(workspace, "Workspace name"),
            "organization_code": _code(organization_code, "Organization code"),
            "entity_code": _code(entity_code, "Entity code"),
            "summary": {
                "total": len(exceptions),
                "high": sum(item["risk_rating"] == "high" for item in exceptions),
                "medium": sum(item["risk_rating"] == "medium" for item in exceptions),
            },
            "exceptions": exceptions,
        }

    def summary(self, *, workspace: str = "default", actor_label: str = "local-cli") -> InventoryCoreSummary:
        require_permission(self.connection, actor_label=actor_label, permission=INVENTORY_READ_PERMISSION)
        workspace_name = _clean_text(workspace, "Workspace name")
        workspace_id = self._workspace_id(workspace_name)
        if workspace_id is None:
            return InventoryCoreSummary(workspace_name, 0, 0, 0, 0, 0, 0, 0, 0)
        try:
            row = self.connection.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM units_of_measure WHERE workspace_id = ?) AS units,
                    (SELECT COUNT(*) FROM inventory_items WHERE workspace_id = ?) AS items,
                    (SELECT COUNT(*) FROM warehouses WHERE workspace_id = ?) AS warehouses,
                    (SELECT COUNT(*) FROM inventory_locations locations
                     JOIN warehouses ON warehouses.id = locations.warehouse_id
                     WHERE warehouses.workspace_id = ?) AS locations,
                    (SELECT COUNT(*) FROM inventory_lots WHERE workspace_id = ?) AS lots,
                    (SELECT COUNT(*) FROM inventory_movements WHERE workspace_id = ? AND status = 'Draft') AS drafts,
                    (SELECT COUNT(*) FROM inventory_movements WHERE workspace_id = ? AND status = 'Posted') AS posted,
                    (SELECT COUNT(*) FROM inventory_movements WHERE workspace_id = ? AND status = 'Voided') AS voided
                """,
                (workspace_id,) * 8,
            ).fetchone()
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to summarize local inventory-core records.") from exc
        if row is None:
            raise PlatformError("Unable to summarize local inventory-core records.")
        return InventoryCoreSummary(
            workspace_name,
            int(row["units"]),
            int(row["items"]),
            int(row["warehouses"]),
            int(row["locations"]),
            int(row["lots"]),
            int(row["drafts"]),
            int(row["posted"]),
            int(row["voided"]),
        )

    def snapshot(self, *, workspace: str = "default", actor_label: str = "local-cli") -> dict[str, object]:
        """Return a bounded, path-free local inventory-core contract."""

        workspace_name = _clean_text(workspace, "Workspace name")
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

    def _validate_movement_integrity(self, movement: Mapping[str, Any], *, check_stock: bool) -> None:
        period = self._period(str(movement["period_id"]), str(movement["workspace_id"]))
        moved_on = _iso_date(movement["movement_date"], "Stored movement date")
        if moved_on is None:
            raise PlatformError("Stored inventory movement date is invalid.")
        self._require_open_period_date(period, moved_on)
        organization = self._organization_by_id(str(movement["organization_id"]), str(movement["workspace_id"]))
        entity = self._entity_by_id(str(movement["legal_entity_id"]), str(organization["id"]))
        if not organization["active"] or not entity["active"]:
            raise PlatformError("Inventory movement contains an inactive organization or legal entity.")
        lines = self._integrity_lines(movement)
        if not 1 <= len(lines) <= MAX_MOVEMENT_LINES:
            raise PlatformError(f"Inventory movements require between 1 and {MAX_MOVEMENT_LINES} lines.")
        for line in lines:
            if not line["item_active"] or line["item_type"] == "Service":
                raise PlatformError("Inventory movement contains an inactive or non-stock item.")
            if line["item_organization_id"] is not None and str(line["item_organization_id"]) != str(
                movement["organization_id"]
            ):
                raise PlatformError("Inventory movement item belongs to a different organization.")
            if not line["uom_active"] or str(line["uom_id"]) != str(line["item_uom_id"]):
                raise PlatformError("Inventory movement contains an inactive or inconsistent unit of measure.")
            if int(line["quantity_precision"]) != int(line["uom_decimal_places"]):
                raise PlatformError("Inventory movement quantity precision no longer matches its item unit.")
            self._validate_integrity_location(line, "from", movement)
            self._validate_integrity_location(line, "to", movement)
            self._validate_line_direction(
                str(movement["movement_type"]),
                {"id": line["from_location_id"]} if line["from_location_id"] else None,
                {"id": line["to_location_id"]} if line["to_location_id"] else None,
            )
            tracking_mode = str(line["tracking_mode"])
            if tracking_mode == "None" and line["inventory_lot_id"] is not None:
                raise PlatformError("Untracked movement item contains a lot or serial reference.")
            if tracking_mode != "None":
                if (
                    line["inventory_lot_id"] is None
                    or not line["lot_active"]
                    or str(line["lot_tracking_type"]) != tracking_mode
                    or str(line["lot_item_id"]) != str(line["item_id"])
                    or str(line["lot_organization_id"]) != str(movement["organization_id"])
                ):
                    raise PlatformError("Tracked movement line contains an inactive or inconsistent lot/serial.")
                if tracking_mode == "Serial" and int(line["quantity_scaled"]) != 10 ** int(line["quantity_precision"]):
                    raise PlatformError("Serial-tracked inventory movement lines must contain exactly one unit.")
        if check_stock:
            self._verify_projected_stock(movement, lines, direction=1)

    def _integrity_lines(self, movement: Mapping[str, Any]) -> list[dict[str, Any]]:
        try:
            rows = self.connection.execute(
                """
                SELECT lines.*,
                       items.organization_id AS item_organization_id,
                       items.item_type, items.tracking_mode, items.active AS item_active,
                       items.uom_id AS item_uom_id,
                       units.active AS uom_active, units.decimal_places AS uom_decimal_places,
                       lots.item_id AS lot_item_id, lots.organization_id AS lot_organization_id,
                       lots.tracking_type AS lot_tracking_type, lots.active AS lot_active,
                       from_locations.active AS from_location_active,
                       from_locations.allow_negative AS from_allow_negative,
                       from_warehouses.active AS from_warehouse_active,
                       from_warehouses.workspace_id AS from_workspace_id,
                       from_warehouses.organization_id AS from_organization_id,
                       from_warehouses.legal_entity_id AS from_entity_id,
                       to_locations.active AS to_location_active,
                       to_locations.allow_negative AS to_allow_negative,
                       to_warehouses.active AS to_warehouse_active,
                       to_warehouses.workspace_id AS to_workspace_id,
                       to_warehouses.organization_id AS to_organization_id,
                       to_warehouses.legal_entity_id AS to_entity_id
                FROM inventory_movement_lines lines
                JOIN inventory_items items ON items.id = lines.item_id
                JOIN units_of_measure units ON units.id = lines.uom_id
                LEFT JOIN inventory_lots lots ON lots.id = lines.inventory_lot_id
                LEFT JOIN inventory_locations from_locations ON from_locations.id = lines.from_location_id
                LEFT JOIN warehouses from_warehouses ON from_warehouses.id = from_locations.warehouse_id
                LEFT JOIN inventory_locations to_locations ON to_locations.id = lines.to_location_id
                LEFT JOIN warehouses to_warehouses ON to_warehouses.id = to_locations.warehouse_id
                WHERE lines.movement_id = ? ORDER BY lines.line_number
                """,
                (movement["id"],),
            ).fetchall()
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to verify local inventory movement lines.") from exc
        return [dict(row) for row in rows]

    def _validate_integrity_location(self, line: Mapping[str, Any], prefix: str, movement: Mapping[str, Any]) -> None:
        location_id = line[f"{prefix}_location_id"]
        if location_id is None:
            return
        if not line[f"{prefix}_location_active"] or not line[f"{prefix}_warehouse_active"]:
            raise PlatformError("Inventory movement contains an inactive location or warehouse.")
        if str(line[f"{prefix}_workspace_id"]) != str(movement["workspace_id"]) or str(
            line[f"{prefix}_organization_id"]
        ) != str(movement["organization_id"]):
            raise PlatformError("Inventory movement location belongs to a different workspace or organization.")
        entity_id = line[f"{prefix}_entity_id"]
        if entity_id is not None and str(entity_id) != str(movement["legal_entity_id"]):
            raise PlatformError("Inventory movement location belongs to a different legal entity.")

    def _verify_projected_stock(
        self,
        movement: Mapping[str, Any],
        lines: Sequence[Mapping[str, Any]],
        *,
        direction: int,
    ) -> None:
        effects: dict[tuple[str, str, str | None], int] = {}
        allow_negative: dict[str, bool] = {}
        serial_effects: dict[tuple[str, str], tuple[int, int]] = {}
        for line in lines:
            item_id = str(line["item_id"])
            lot_id = str(line["inventory_lot_id"]) if line["inventory_lot_id"] is not None else None
            quantity = int(line["quantity_scaled"]) * direction
            if line["from_location_id"] is not None:
                location_id = str(line["from_location_id"])
                key = (location_id, item_id, lot_id)
                effects[key] = effects.get(key, 0) - quantity
                allow_negative[location_id] = bool(line["from_allow_negative"])
            if line["to_location_id"] is not None:
                location_id = str(line["to_location_id"])
                key = (location_id, item_id, lot_id)
                effects[key] = effects.get(key, 0) + quantity
                allow_negative[location_id] = bool(line["to_allow_negative"])
            if line["tracking_mode"] == "Serial" and lot_id is not None:
                serial_key = (item_id, lot_id)
                current_effect, precision = serial_effects.get(serial_key, (0, int(line["quantity_precision"])))
                serial_effects[serial_key] = (
                    current_effect
                    + (quantity if line["to_location_id"] is not None else 0)
                    - (quantity if line["from_location_id"] is not None else 0),
                    precision,
                )
        for (location_id, item_id, lot_id), effect in effects.items():
            current = self._stock_quantity(
                workspace_id=str(movement["workspace_id"]),
                organization_id=str(movement["organization_id"]),
                entity_id=str(movement["legal_entity_id"]),
                location_id=location_id,
                item_id=item_id,
                lot_id=lot_id,
            )
            if current + effect < 0 and not allow_negative.get(location_id, False):
                raise PlatformError("Inventory movement would create negative stock in a protected location.")
        for (item_id, lot_id), (effect, precision) in serial_effects.items():
            current = self._serial_quantity(
                workspace_id=str(movement["workspace_id"]),
                organization_id=str(movement["organization_id"]),
                entity_id=str(movement["legal_entity_id"]),
                item_id=item_id,
                lot_id=lot_id,
            )
            if current + effect not in {0, 10**precision}:
                raise PlatformError("Serial tracking permits exactly zero or one on-hand unit per serial number.")

    def _stock_quantity(
        self,
        *,
        workspace_id: str,
        organization_id: str,
        entity_id: str,
        location_id: str,
        item_id: str,
        lot_id: str | None,
    ) -> int:
        try:
            row = self.connection.execute(
                """
                SELECT COALESCE(SUM(
                    CASE WHEN lines.to_location_id = ? THEN lines.quantity_scaled ELSE 0 END -
                    CASE WHEN lines.from_location_id = ? THEN lines.quantity_scaled ELSE 0 END
                ), 0) AS quantity
                FROM inventory_movement_lines lines
                JOIN inventory_movements movements ON movements.id = lines.movement_id
                WHERE movements.workspace_id = ? AND movements.organization_id = ?
                  AND movements.legal_entity_id = ? AND movements.status = 'Posted'
                  AND lines.item_id = ?
                  AND ((lines.inventory_lot_id IS NULL AND ? IS NULL) OR lines.inventory_lot_id = ?)
                  AND (lines.to_location_id = ? OR lines.from_location_id = ?)
                """,
                (
                    location_id,
                    location_id,
                    workspace_id,
                    organization_id,
                    entity_id,
                    item_id,
                    lot_id,
                    lot_id,
                    location_id,
                    location_id,
                ),
            ).fetchone()
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to verify local on-hand stock.") from exc
        return int(row["quantity"] if row is not None else 0)

    def _serial_quantity(
        self,
        *,
        workspace_id: str,
        organization_id: str,
        entity_id: str,
        item_id: str,
        lot_id: str,
    ) -> int:
        try:
            row = self.connection.execute(
                """
                SELECT COALESCE(SUM(
                    CASE WHEN lines.to_location_id IS NOT NULL THEN lines.quantity_scaled ELSE 0 END -
                    CASE WHEN lines.from_location_id IS NOT NULL THEN lines.quantity_scaled ELSE 0 END
                ), 0) AS quantity
                FROM inventory_movement_lines lines
                JOIN inventory_movements movements ON movements.id = lines.movement_id
                WHERE movements.workspace_id = ? AND movements.organization_id = ?
                  AND movements.legal_entity_id = ? AND movements.status = 'Posted'
                  AND lines.item_id = ? AND lines.inventory_lot_id = ?
                """,
                (workspace_id, organization_id, entity_id, item_id, lot_id),
            ).fetchone()
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to verify local serial-number stock.") from exc
        return int(row["quantity"] if row is not None else 0)

    @staticmethod
    def _validate_line_direction(
        movement_type: str,
        from_location: Mapping[str, object] | None,
        to_location: Mapping[str, object] | None,
    ) -> None:
        if from_location is not None and to_location is not None and from_location["id"] == to_location["id"]:
            raise PlatformError("Inventory movement source and destination locations must differ.")
        valid = (
            (movement_type == "Receipt" and from_location is None and to_location is not None)
            or (movement_type == "Delivery" and from_location is not None and to_location is None)
            or (movement_type == "Transfer" and from_location is not None and to_location is not None)
            or (movement_type == "Adjustment" and (from_location is None) != (to_location is None))
        )
        if not valid:
            raise PlatformError(
                "Receipt lines require only a destination; Delivery only a source; Transfer both; Adjustment exactly one."
            )

    @staticmethod
    def _require_open_period_date(period: Mapping[str, object], moved_on: date) -> None:
        if period["status"] != "Open":
            raise PlatformError("Inventory movements require an Open fiscal period.")
        start = _iso_date(period["start_date"], "Stored period start date")
        end = _iso_date(period["end_date"], "Stored period end date")
        if start is None or end is None:
            raise PlatformError("Stored fiscal period dates are invalid.")
        if not start <= moved_on <= end:
            raise PlatformError("Movement date must fall inside the selected fiscal period.")

    def _optional_location_reference(
        self,
        workspace_id: str,
        organization_id: str,
        entity_id: str,
        value: object,
    ) -> dict[str, Any] | None:
        reference = _clean_text(value, "Location reference", maximum=129, required=False)
        if not reference:
            return None
        parts = reference.split("/")
        if len(parts) != 2:
            raise PlatformError("Location references must use WAREHOUSE/LOCATION format.")
        warehouse = self._warehouse(workspace_id, organization_id, _code(parts[0], "Warehouse code"))
        if not warehouse["active"]:
            raise PlatformError("Movement locations require an active warehouse.")
        if warehouse["legal_entity_id"] is not None and str(warehouse["legal_entity_id"]) != entity_id:
            raise PlatformError("Movement warehouse belongs to a different legal entity.")
        location = self._location(str(warehouse["id"]), _code(parts[1], "Location code"))
        if not location["active"]:
            raise PlatformError("Movement locations must be active.")
        return location

    @staticmethod
    def _location_label(warehouse_code: object, location_code: object) -> str:
        if warehouse_code is None or location_code is None:
            return ""
        return f"{warehouse_code}/{location_code}"

    def _workspace_id(self, workspace: str) -> str | None:
        name = _clean_text(workspace, "Workspace name")
        try:
            row = self.connection.execute("SELECT id FROM workspaces WHERE name = ?", (name,)).fetchone()
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to read the local workspace reference.") from exc
        return str(row["id"]) if row is not None else None

    def _organization(self, workspace_id: str, code: str) -> dict[str, Any]:
        try:
            row = self.connection.execute(
                "SELECT * FROM organizations WHERE workspace_id = ? AND organization_code = ?",
                (workspace_id, code),
            ).fetchone()
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to read the local organization reference.") from exc
        if row is None:
            raise PlatformError("Organization reference was not found.")
        return _public_record(row)

    def _organization_by_id(self, organization_id: str, workspace_id: str) -> dict[str, Any]:
        try:
            row = self.connection.execute(
                "SELECT * FROM organizations WHERE id = ? AND workspace_id = ?",
                (organization_id, workspace_id),
            ).fetchone()
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to read the stored organization reference.") from exc
        if row is None:
            raise PlatformError("Stored organization reference was not found.")
        return _public_record(row)

    def _entity(self, organization_id: str, code: str) -> dict[str, Any]:
        try:
            row = self.connection.execute(
                "SELECT * FROM legal_entities WHERE organization_id = ? AND entity_code = ?",
                (organization_id, code),
            ).fetchone()
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to read the local legal-entity reference.") from exc
        if row is None:
            raise PlatformError("Legal-entity reference was not found.")
        return _public_record(row)

    def _entity_by_id(self, entity_id: str, organization_id: str) -> dict[str, Any]:
        try:
            row = self.connection.execute(
                "SELECT * FROM legal_entities WHERE id = ? AND organization_id = ?",
                (entity_id, organization_id),
            ).fetchone()
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to read the stored legal-entity reference.") from exc
        if row is None:
            raise PlatformError("Stored legal-entity reference was not found.")
        return _public_record(row)

    def _period(self, period_id: str, workspace_id: str) -> dict[str, Any]:
        identifier = _clean_text(period_id, "Period identifier")
        try:
            row = self.connection.execute(
                "SELECT * FROM periods WHERE id = ? AND workspace_id = ?", (identifier, workspace_id)
            ).fetchone()
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to read the local fiscal-period reference.") from exc
        if row is None:
            raise PlatformError("Fiscal-period reference was not found.")
        return dict(row)

    def _uom(self, workspace_id: str, code: str) -> dict[str, Any]:
        try:
            row = self.connection.execute(
                "SELECT * FROM units_of_measure WHERE workspace_id = ? AND uom_code = ?", (workspace_id, code)
            ).fetchone()
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to read the local unit of measure.") from exc
        if row is None:
            raise PlatformError("Unit-of-measure reference was not found.")
        return _public_record(row)

    def _account(self, workspace_id: str, code: str) -> dict[str, Any]:
        try:
            row = self.connection.execute(
                """
                SELECT accounts.*, charts_of_accounts.organization_id AS chart_organization_id
                FROM accounts
                JOIN charts_of_accounts ON charts_of_accounts.id = accounts.chart_id
                WHERE accounts.workspace_id = ? AND accounts.account_code = ?
                """,
                (workspace_id, code),
            ).fetchone()
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to read the local inventory account reference.") from exc
        if row is None:
            raise PlatformError("Inventory account reference was not found.")
        return _public_record(row)

    def _item(self, workspace_id: str, code: str) -> dict[str, Any]:
        try:
            row = self.connection.execute(
                """
                SELECT items.*, units.uom_code, units.decimal_places, units.active AS uom_active,
                       organizations.organization_code,
                       accounts.account_code AS inventory_account_code
                FROM inventory_items items
                JOIN units_of_measure units ON units.id = items.uom_id
                LEFT JOIN organizations ON organizations.id = items.organization_id
                LEFT JOIN accounts ON accounts.id = items.inventory_account_id
                WHERE items.workspace_id = ? AND items.item_code = ?
                """,
                (workspace_id, code),
            ).fetchone()
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to read the local inventory item.") from exc
        if row is None:
            raise PlatformError("Inventory item reference was not found.")
        return _public_record(row)

    def _warehouse(self, workspace_id: str, organization_id: str, code: str) -> dict[str, Any]:
        try:
            row = self.connection.execute(
                """
                SELECT warehouses.*, organizations.organization_code, legal_entities.entity_code
                FROM warehouses
                JOIN organizations ON organizations.id = warehouses.organization_id
                LEFT JOIN legal_entities ON legal_entities.id = warehouses.legal_entity_id
                WHERE warehouses.workspace_id = ? AND warehouses.organization_id = ?
                  AND warehouses.warehouse_code = ?
                """,
                (workspace_id, organization_id, code),
            ).fetchone()
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to read the local warehouse.") from exc
        if row is None:
            raise PlatformError("Warehouse reference was not found.")
        return _public_record(row)

    def _location(self, warehouse_id: str, code: str) -> dict[str, Any]:
        try:
            row = self.connection.execute(
                """
                SELECT locations.*, parents.location_code AS parent_location_code
                FROM inventory_locations locations
                LEFT JOIN inventory_locations parents ON parents.id = locations.parent_location_id
                WHERE locations.warehouse_id = ? AND locations.location_code = ?
                """,
                (warehouse_id, code),
            ).fetchone()
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to read the local inventory location.") from exc
        if row is None:
            raise PlatformError("Inventory location reference was not found.")
        return _public_record(row)

    def _lot(self, item_id: str, organization_id: str, code: str) -> dict[str, Any]:
        try:
            row = self.connection.execute(
                """
                SELECT lots.*, items.item_code, organizations.organization_code
                FROM inventory_lots lots
                JOIN inventory_items items ON items.id = lots.item_id
                JOIN organizations ON organizations.id = lots.organization_id
                WHERE lots.item_id = ? AND lots.organization_id = ? AND lots.lot_serial_code = ?
                """,
                (item_id, organization_id, code),
            ).fetchone()
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to read the local lot or serial reference.") from exc
        if row is None:
            raise PlatformError("Lot or serial reference was not found.")
        return _public_record(row)

    def _movement(self, movement_id: str) -> dict[str, Any]:
        identifier = _clean_text(movement_id, "Movement identifier")
        try:
            row = self.connection.execute(
                """
                SELECT movements.*, organizations.organization_code, entities.entity_code,
                       periods.name AS period_name
                FROM inventory_movements movements
                JOIN organizations ON organizations.id = movements.organization_id
                JOIN legal_entities entities ON entities.id = movements.legal_entity_id
                JOIN periods ON periods.id = movements.period_id
                WHERE movements.id = ?
                """,
                (identifier,),
            ).fetchone()
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to read the local inventory movement.") from exc
        if row is None:
            raise PlatformError("Inventory movement reference was not found.")
        return dict(row)

    def _location_is_descendant(self, location_id: str, proposed_parent_id: str) -> bool:
        try:
            row = self.connection.execute(
                """
                WITH RECURSIVE descendants(id) AS (
                    SELECT id FROM inventory_locations WHERE parent_location_id = ?
                    UNION ALL
                    SELECT locations.id FROM inventory_locations locations
                    JOIN descendants ON locations.parent_location_id = descendants.id
                )
                SELECT 1 FROM descendants WHERE id = ? LIMIT 1
                """,
                (location_id, proposed_parent_id),
            ).fetchone()
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to validate inventory location hierarchy.") from exc
        return row is not None
