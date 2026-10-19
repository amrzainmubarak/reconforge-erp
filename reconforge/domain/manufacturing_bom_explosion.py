"""Advanced Multi-Level BOM Explosion, Engineering Revision, and MRP Netting Engine.

Enforces zero-float mass/quantity conservation with integer basis-point scrap factors,
cycle detection, effective-date filtering, and lot-size replenishment rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

from reconforge.domain.finance_posting import text
from reconforge.domain.manufacturing_execution import exact_integer, fail

BOMStatus = Literal["draft", "approved", "obsolete"]
ItemType = Literal["raw_material", "subassembly", "finished_good"]

MAX_BOM_DEPTH = 20
BPS_DENOMINATOR = 10_000


@dataclass(frozen=True)
class BOMComponentLine:
    """A single component requirement within a parent BOM."""

    line_number: int
    component_item_id: str
    component_name: str
    component_type: ItemType
    quantity_per_parent: int  # Exact integer units required per 1 parent
    scrap_factor_bps: int = 0  # Expected scrap in basis points (e.g. 500 = 5.00%)
    substitute_item_id: str | None = None
    substitute_ratio_bps: int = 10_000  # 1:1 substitution ratio default

    def __post_init__(self) -> None:
        if self.line_number < 1:
            fail("Line number must be >= 1.", "bom_line_invalid")
        text(self.component_item_id, "component_item_id", maximum=64)
        exact_integer(self.quantity_per_parent, positive=True)
        if not (0 <= self.scrap_factor_bps <= 50_000):  # max 500% scrap
            fail("Scrap factor must be 0..50,000 basis points.", "bom_scrap_invalid")
        if self.substitute_item_id:
            text(self.substitute_item_id, "substitute_item_id", maximum=64)


@dataclass(frozen=True)
class BillOfMaterials:
    """Versioned and effective-dated Bill of Materials for an item."""

    bom_id: str
    item_id: str
    revision: str  # e.g., "REV-B"
    status: BOMStatus
    effective_from: str  # ISO date
    effective_to: str | None  # Optional ISO date
    base_quantity: int  # Typically 1
    components: tuple[BOMComponentLine, ...]

    def __post_init__(self) -> None:
        text(self.bom_id, "bom_id", maximum=64)
        text(self.item_id, "item_id", maximum=64)
        text(self.revision, "revision", maximum=32)
        date.fromisoformat(self.effective_from)
        if self.effective_to and date.fromisoformat(self.effective_from) > date.fromisoformat(self.effective_to):
            fail("effective_from cannot exceed effective_to.", "bom_date_invalid")
        exact_integer(self.base_quantity, positive=True)
        if not self.components:
            fail("BOM must contain at least one component.", "bom_components_empty")


@dataclass(frozen=True)
class ExplodedRequirement:
    """An exploded component requirement at an indented level."""

    depth: int
    parent_item_id: str
    item_id: str
    item_type: ItemType
    path: str  # e.g., "FG-001 -> SUB-010 -> RAW-100"
    gross_quantity: int
    scrap_quantity: int
    total_required_quantity: int


@dataclass(frozen=True)
class NetMRPRequirement:
    """Net shortage and suggested replenishment after netting on-hand and on-order."""

    item_id: str
    item_type: ItemType
    gross_required: int
    on_hand: int
    scheduled_receipts: int
    net_shortage: int
    planned_order_quantity: int  # Rounded up to lot multiple/minimum


class BOMExplosionEngine:
    """Traverses multi-level BOM hierarchies with cycle detection and netting."""

    def __init__(self, boms: list[BillOfMaterials]) -> None:
        # Index approved BOMs by item_id and revision
        self._boms: dict[tuple[str, str], BillOfMaterials] = {}
        self._latest_approved_bom: dict[str, BillOfMaterials] = {}

        for b in boms:
            self._boms[(b.item_id, b.revision)] = b
            if b.status == "approved":
                self._latest_approved_bom[b.item_id] = b

    def explode(
        self,
        item_id: str,
        required_quantity: int,
        as_of_date: str,
        specific_revision: str | None = None,
    ) -> list[ExplodedRequirement]:
        exact_integer(required_quantity, positive=True)
        req_d = date.fromisoformat(as_of_date)

        results: list[ExplodedRequirement] = []
        visited_path: list[str] = []

        def _traverse(current_item: str, multiplier: int, depth: int, parent: str) -> None:
            if depth > MAX_BOM_DEPTH:
                fail(f"Maximum BOM recursion depth {MAX_BOM_DEPTH} exceeded.", "bom_depth_exceeded")
            if current_item in visited_path:
                cycle = " -> ".join(visited_path + [current_item])
                fail(f"Circular dependency detected: {cycle}", "bom_cycle_detected")

            visited_path.append(current_item)

            bom = self._boms.get((current_item, specific_revision)) if specific_revision and depth == 0 else self._latest_approved_bom.get(current_item)

            if bom is not None:
                # Check date validity
                from_d = date.fromisoformat(bom.effective_from)
                if req_d < from_d:
                    fail(f"BOM for {current_item} not effective on {as_of_date}.", "bom_effective_invalid")
                if bom.effective_to and req_d > date.fromisoformat(bom.effective_to):
                    fail(f"BOM for {current_item} expired on {bom.effective_to}.", "bom_effective_invalid")

                for comp in bom.components:
                    base_qty = (comp.quantity_per_parent * multiplier + (bom.base_quantity // 2)) // bom.base_quantity
                    scrap_qty = (base_qty * comp.scrap_factor_bps + (BPS_DENOMINATOR // 2)) // BPS_DENOMINATOR
                    total_qty = base_qty + scrap_qty

                    path_str = " -> ".join(visited_path + [comp.component_item_id])

                    results.append(
                        ExplodedRequirement(
                            depth=depth + 1,
                            parent_item_id=current_item,
                            item_id=comp.component_item_id,
                            item_type=comp.component_type,
                            path=path_str,
                            gross_quantity=base_qty,
                            scrap_quantity=scrap_qty,
                            total_required_quantity=total_qty,
                        )
                    )

                    # If component is a subassembly, recurse deeper
                    if comp.component_type == "subassembly":
                        _traverse(comp.component_item_id, total_qty, depth + 1, current_item)

            visited_path.pop()

        _traverse(item_id, required_quantity, 0, "")
        return results

    def calculate_net_requirements(
        self,
        exploded: list[ExplodedRequirement],
        inventory_on_hand: dict[str, int],
        scheduled_receipts: dict[str, int],
        lot_sizing: dict[str, tuple[int, int]] | None = None,  # item_id -> (min_lot, lot_multiple)
    ) -> list[NetMRPRequirement]:
        """Aggregate total gross demand per component and calculate net shortages."""
        lot_rules = lot_sizing or {}

        # Sum demand by item_id
        gross_totals: dict[str, tuple[ItemType, int]] = {}
        for req in exploded:
            current_type, current_sum = gross_totals.get(req.item_id, (req.item_type, 0))
            gross_totals[req.item_id] = (req.item_type, current_sum + req.total_required_quantity)

        net_results: list[NetMRPRequirement] = []

        for item_id, (item_type, gross_qty) in sorted(gross_totals.items()):
            on_hand = inventory_on_hand.get(item_id, 0)
            on_order = scheduled_receipts.get(item_id, 0)
            exact_integer(on_hand, positive=False)
            exact_integer(on_order, positive=False)

            available = on_hand + on_order
            shortage = max(0, gross_qty - available)

            # Apply lot sizing: min_lot and lot_multiple
            min_lot, lot_multiple = lot_rules.get(item_id, (1, 1))
            if shortage == 0:
                planned_qty = 0
            else:
                planned = max(shortage, min_lot)
                if lot_multiple > 1:
                    remainder = planned % lot_multiple
                    if remainder != 0:
                        planned += lot_multiple - remainder
                planned_qty = planned

            net_results.append(
                NetMRPRequirement(
                    item_id=item_id,
                    item_type=item_type,
                    gross_required=gross_qty,
                    on_hand=on_hand,
                    scheduled_receipts=on_order,
                    net_shortage=shortage,
                    planned_order_quantity=planned_qty,
                )
            )

        return net_results
