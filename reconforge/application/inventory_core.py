"""Backend-neutral governed inventory-core application boundary."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any, Protocol

DEFAULT_LIST_LIMIT = 500
MAX_LIST_LIMIT = 100_000


@dataclass(frozen=True)
class InventoryCoreSummary:
    """Counts for one workspace without a persistence dependency."""

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


class InventoryCoreRepositoryProtocol(Protocol):
    """Complete persistence and policy port for governed inventory state."""

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
    ) -> dict[str, Any]: ...
    def list_uoms(
        self,
        *,
        workspace: str = "default",
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]: ...
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
    ) -> dict[str, Any]: ...
    def list_items(
        self,
        *,
        workspace: str = "default",
        organization_code: str = "",
        active_only: bool = False,
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]: ...
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
    ) -> dict[str, Any]: ...
    def list_warehouses(
        self,
        *,
        workspace: str = "default",
        organization_code: str = "",
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]: ...
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
    ) -> dict[str, Any]: ...
    def list_locations(
        self,
        *,
        workspace: str = "default",
        organization_code: str = "",
        warehouse_code: str = "",
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]: ...
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
    ) -> dict[str, Any]: ...
    def list_lots(
        self,
        *,
        workspace: str = "default",
        organization_code: str = "",
        item_code: str = "",
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]: ...
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
    ) -> dict[str, Any]: ...
    def post_movement(self, movement_id: str, *, reason: str, actor_label: str = "local-cli") -> dict[str, Any]: ...
    def void_movement(self, movement_id: str, *, reason: str, actor_label: str = "local-cli") -> dict[str, Any]: ...
    def get_movement(self, movement_id: str, *, actor_label: str = "local-cli") -> dict[str, Any]: ...
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
    ) -> list[dict[str, Any]]: ...
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
    ) -> dict[str, object]: ...
    def control_exceptions(
        self,
        *,
        organization_code: str,
        entity_code: str,
        workspace: str = "default",
        as_of: str = "",
        actor_label: str = "local-cli",
    ) -> dict[str, object]: ...
    def summary(self, *, workspace: str = "default", actor_label: str = "local-cli") -> InventoryCoreSummary: ...
    def snapshot(self, *, workspace: str = "default", actor_label: str = "local-cli") -> dict[str, object]: ...


class InventoryCoreApplicationService:
    """Coordinate inventory use cases without importing a database adapter."""

    def __init__(self, repository: InventoryCoreRepositoryProtocol) -> None:
        self.repository = repository

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
        return self.repository.upsert_uom(
            uom_code=uom_code,
            name=name,
            workspace=workspace,
            category=category,
            decimal_places=decimal_places,
            active=active,
            actor_label=actor_label,
        )

    def list_uoms(
        self,
        *,
        workspace: str = "default",
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]:
        return self.repository.list_uoms(workspace=workspace, limit=limit, offset=offset, actor_label=actor_label)

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
        return self.repository.upsert_item(
            item_code=item_code,
            name=name,
            workspace=workspace,
            organization_code=organization_code,
            uom_code=uom_code,
            item_type=item_type,
            tracking_mode=tracking_mode,
            inventory_account_code=inventory_account_code,
            description=description,
            active=active,
            actor_label=actor_label,
        )

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
        return self.repository.list_items(
            workspace=workspace,
            organization_code=organization_code,
            active_only=active_only,
            limit=limit,
            offset=offset,
            actor_label=actor_label,
        )

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
        return self.repository.upsert_warehouse(
            warehouse_code=warehouse_code,
            name=name,
            organization_code=organization_code,
            workspace=workspace,
            entity_code=entity_code,
            active=active,
            actor_label=actor_label,
        )

    def list_warehouses(
        self,
        *,
        workspace: str = "default",
        organization_code: str = "",
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]:
        return self.repository.list_warehouses(
            workspace=workspace,
            organization_code=organization_code,
            limit=limit,
            offset=offset,
            actor_label=actor_label,
        )

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
        return self.repository.upsert_location(
            warehouse_code=warehouse_code,
            location_code=location_code,
            name=name,
            organization_code=organization_code,
            workspace=workspace,
            parent_location_code=parent_location_code,
            location_type=location_type,
            allow_negative=allow_negative,
            active=active,
            actor_label=actor_label,
        )

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
        return self.repository.list_locations(
            workspace=workspace,
            organization_code=organization_code,
            warehouse_code=warehouse_code,
            limit=limit,
            offset=offset,
            actor_label=actor_label,
        )

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
        return self.repository.upsert_lot(
            item_code=item_code,
            lot_serial_code=lot_serial_code,
            organization_code=organization_code,
            workspace=workspace,
            manufactured_on=manufactured_on,
            expires_on=expires_on,
            active=active,
            actor_label=actor_label,
        )

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
        return self.repository.list_lots(
            workspace=workspace,
            organization_code=organization_code,
            item_code=item_code,
            limit=limit,
            offset=offset,
            actor_label=actor_label,
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
        return self.repository.create_movement(
            movement_number=movement_number,
            movement_type=movement_type,
            organization_code=organization_code,
            entity_code=entity_code,
            period_id=period_id,
            movement_date=movement_date,
            description=description,
            lines=lines,
            workspace=workspace,
            source_reference=source_reference,
            source_type=source_type,
            actor_label=actor_label,
        )

    def post_movement(self, movement_id: str, *, reason: str, actor_label: str = "local-cli") -> dict[str, Any]:
        return self.repository.post_movement(movement_id, reason=reason, actor_label=actor_label)

    def void_movement(self, movement_id: str, *, reason: str, actor_label: str = "local-cli") -> dict[str, Any]:
        return self.repository.void_movement(movement_id, reason=reason, actor_label=actor_label)

    def get_movement(self, movement_id: str, *, actor_label: str = "local-cli") -> dict[str, Any]:
        return self.repository.get_movement(movement_id, actor_label=actor_label)

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
        return self.repository.list_movements(
            workspace=workspace,
            organization_code=organization_code,
            entity_code=entity_code,
            period_id=period_id,
            status=status,
            limit=limit,
            offset=offset,
            actor_label=actor_label,
        )

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
        return self.repository.on_hand(
            organization_code=organization_code,
            entity_code=entity_code,
            workspace=workspace,
            item_code=item_code,
            warehouse_code=warehouse_code,
            include_zero=include_zero,
            limit=limit,
            offset=offset,
            actor_label=actor_label,
        )

    def control_exceptions(
        self,
        *,
        organization_code: str,
        entity_code: str,
        workspace: str = "default",
        as_of: str = "",
        actor_label: str = "local-cli",
    ) -> dict[str, object]:
        return self.repository.control_exceptions(
            organization_code=organization_code,
            entity_code=entity_code,
            workspace=workspace,
            as_of=as_of,
            actor_label=actor_label,
        )

    def summary(self, *, workspace: str = "default", actor_label: str = "local-cli") -> InventoryCoreSummary:
        return self.repository.summary(workspace=workspace, actor_label=actor_label)

    def snapshot(self, *, workspace: str = "default", actor_label: str = "local-cli") -> dict[str, object]:
        return self.repository.snapshot(workspace=workspace, actor_label=actor_label)
