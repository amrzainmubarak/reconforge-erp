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
from reconforge.domain.manufacturing_supply_plan import (
    MRPShortageRequisition,
    generate_mrp_shortage_requisitions,
)

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
    uom_id: str = "EA"
    uom_conversion_factor_bps: int = 10_000  # Scaling factor in basis points (10000 = 1.0)
    eco_number: str | None = None
    change_reason: str | None = None

    def __post_init__(self) -> None:
        if self.line_number < 1:
            fail("Line number must be >= 1.", "bom_line_invalid")
        text(self.component_item_id, "component_item_id", maximum=64)
        exact_integer(self.quantity_per_parent, positive=True)
        if not (0 <= self.scrap_factor_bps <= 50_000):  # max 500% scrap
            fail("Scrap factor must be 0..50,000 basis points.", "bom_scrap_invalid")
        if self.substitute_item_id:
            text(self.substitute_item_id, "substitute_item_id", maximum=64)
        text(self.uom_id, "uom_id", maximum=32)
        exact_integer(self.uom_conversion_factor_bps, positive=True)
        if not (1 <= self.uom_conversion_factor_bps <= 1_000_000):
            fail("uom_conversion_factor_bps must be between 1 and 1,000,000.", "bom_uom_factor_invalid")
        if self.eco_number is not None:
            text(self.eco_number, "eco_number", maximum=64)
        if self.change_reason is not None:
            text(self.change_reason, "change_reason", maximum=255)


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
    eco_number: str | None = None
    change_reason: str | None = None

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
        if self.eco_number is not None:
            text(self.eco_number, "eco_number", maximum=64)
        if self.change_reason is not None:
            text(self.change_reason, "change_reason", maximum=255)


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
    is_substituted: bool = False
    original_item_id: str | None = None


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
    """Traverses multi-level BOM hierarchies with cycle detection, revision selection, and netting."""

    def __init__(self, boms: list[BillOfMaterials]) -> None:
        # Index approved BOMs by (item_id, revision) and item_id
        self._boms: dict[tuple[str, str], BillOfMaterials] = {}
        self._boms_by_item: dict[str, list[BillOfMaterials]] = {}

        for b in boms:
            self._boms[(b.item_id, b.revision)] = b
            self._boms_by_item.setdefault(b.item_id, []).append(b)

    def _find_effective_bom(
        self,
        item_id: str,
        as_of_date: str,
        specific_revision: str | None = None,
    ) -> BillOfMaterials | None:
        """Finds date-effective approved BOM for an item matching effective_from <= as_of_date <= effective_to."""
        item_boms = self._boms_by_item.get(item_id, [])
        if not item_boms:
            return None

        req_d = date.fromisoformat(as_of_date)

        if specific_revision is not None:
            target = self._boms.get((item_id, specific_revision))
            if target is None:
                return None
            if target.status != "approved":
                fail(f"BOM for {item_id} revision {specific_revision} is not approved (status={target.status}).", "bom_not_approved")
            from_d = date.fromisoformat(target.effective_from)
            to_d = date.fromisoformat(target.effective_to) if target.effective_to else None
            if req_d < from_d:
                fail(f"BOM for {item_id} (revision {specific_revision}) not effective on {as_of_date}.", "bom_effective_invalid")
            if to_d and req_d > to_d:
                fail(f"BOM for {item_id} (revision {specific_revision}) expired on {target.effective_to}.", "bom_effective_invalid")
            return target

        approved = [b for b in item_boms if b.status == "approved"]
        if not approved:
            return None

        valid_candidates = []
        for b in approved:
            from_d = date.fromisoformat(b.effective_from)
            to_d = date.fromisoformat(b.effective_to) if b.effective_to else None
            if from_d <= req_d and (to_d is None or req_d <= to_d):
                valid_candidates.append(b)

        if not valid_candidates:
            fail(f"No approved BOM for {item_id} effective on {as_of_date}.", "bom_effective_invalid")

        valid_candidates.sort(
            key=lambda b: (date.fromisoformat(b.effective_from), b.revision),
            reverse=True,
        )
        return valid_candidates[0]

    def explode(
        self,
        item_id: str,
        required_quantity: int,
        as_of_date: str,
        specific_revision: str | None = None,
        preferred_substitutions: frozenset[str] | set[str] | dict[str, str] | None = None,
    ) -> list[ExplodedRequirement]:
        exact_integer(required_quantity, positive=True)
        date.fromisoformat(as_of_date)

        results: list[ExplodedRequirement] = []
        visited_path: list[str] = []

        def _traverse(current_item: str, multiplier: int, depth: int, parent: str) -> None:
            if depth > MAX_BOM_DEPTH:
                fail(f"Maximum BOM recursion depth {MAX_BOM_DEPTH} exceeded.", "bom_depth_exceeded")
            if current_item in visited_path:
                cycle = " -> ".join(visited_path + [current_item])
                fail(f"Circular dependency detected: {cycle}", "bom_cycle_detected")

            visited_path.append(current_item)

            bom = self._find_effective_bom(current_item, as_of_date, specific_revision if depth == 0 else None)

            if bom is not None:
                for comp in bom.components:
                    # Check for substitution
                    should_substitute = False
                    if preferred_substitutions:
                        if isinstance(preferred_substitutions, (set, frozenset, list, tuple)):
                            should_substitute = comp.component_item_id in preferred_substitutions
                        elif isinstance(preferred_substitutions, dict):
                            sub_target = preferred_substitutions.get(comp.component_item_id)
                            should_substitute = (sub_target == comp.substitute_item_id or sub_target is True or sub_target == "*")

                    if should_substitute:
                        if not comp.substitute_item_id:
                            fail(f"No substitute item configured for component {comp.component_item_id}.", "bom_no_substitute")
                        effective_item_id = comp.substitute_item_id
                        is_sub = True
                        orig_item_id = comp.component_item_id
                        ratio_bps = comp.substitute_ratio_bps
                    else:
                        effective_item_id = comp.component_item_id
                        is_sub = False
                        orig_item_id = None
                        ratio_bps = BPS_DENOMINATOR

                    base_qty = (comp.quantity_per_parent * multiplier + (bom.base_quantity // 2)) // bom.base_quantity
                    if comp.uom_conversion_factor_bps != BPS_DENOMINATOR:
                        base_qty = (base_qty * comp.uom_conversion_factor_bps + (BPS_DENOMINATOR // 2)) // BPS_DENOMINATOR
                    if is_sub:
                        scaled_base_qty = (base_qty * ratio_bps + (BPS_DENOMINATOR // 2)) // BPS_DENOMINATOR
                    else:
                        scaled_base_qty = base_qty

                    scrap_qty = (scaled_base_qty * comp.scrap_factor_bps + (BPS_DENOMINATOR // 2)) // BPS_DENOMINATOR
                    total_qty = scaled_base_qty + scrap_qty

                    path_str = " -> ".join(visited_path + [effective_item_id])

                    results.append(
                        ExplodedRequirement(
                            depth=depth + 1,
                            parent_item_id=current_item,
                            item_id=effective_item_id,
                            item_type=comp.component_type,
                            path=path_str,
                            gross_quantity=scaled_base_qty,
                            scrap_quantity=scrap_qty,
                            total_required_quantity=total_qty,
                            is_substituted=is_sub,
                            original_item_id=orig_item_id,
                        )
                    )

                    # If component is a subassembly, recurse deeper
                    if comp.component_type == "subassembly":
                        _traverse(effective_item_id, total_qty, depth + 1, current_item)

            visited_path.pop()

        _traverse(item_id, required_quantity, 0, "")
        return results

    def calculate_net_requirements(
        self,
        exploded: list[ExplodedRequirement],
        inventory_on_hand: dict[str, int],
        scheduled_receipts: dict[str, int],
        lot_sizing: dict[str, tuple[int, int]] | None = None,  # item_id -> (min_lot, lot_multiple)
        substitute_rules: dict[str, tuple[str, int]] | None = None,  # primary_item_id -> (substitute_item_id, substitute_ratio_bps)
    ) -> list[NetMRPRequirement]:
        """Aggregate total gross demand per component and calculate net shortages with substitute netting."""
        lot_rules = lot_sizing or {}

        # Build substitute mapping
        effective_sub_rules: dict[str, tuple[str, int]] = {}
        for boms in self._boms_by_item.values():
            for bom in boms:
                for comp in bom.components:
                    if comp.substitute_item_id and comp.component_item_id not in effective_sub_rules:
                        effective_sub_rules[comp.component_item_id] = (comp.substitute_item_id, comp.substitute_ratio_bps)
        if substitute_rules:
            effective_sub_rules.update(substitute_rules)

        # Working inventory pool to prevent duplicate substitute consumption
        on_hand_pool = dict(inventory_on_hand)
        on_order_pool = dict(scheduled_receipts)

        # Sum demand by item_id
        gross_totals: dict[str, tuple[ItemType, int]] = {}
        for req in exploded:
            current_type, current_sum = gross_totals.get(req.item_id, (req.item_type, 0))
            gross_totals[req.item_id] = (req.item_type, current_sum + req.total_required_quantity)

        net_results: list[NetMRPRequirement] = []

        for item_id, (item_type, gross_qty) in sorted(gross_totals.items()):
            on_hand = on_hand_pool.get(item_id, 0)
            on_order = on_order_pool.get(item_id, 0)
            exact_integer(on_hand, positive=False)
            exact_integer(on_order, positive=False)

            available = on_hand + on_order
            initial_shortage = max(0, gross_qty - available)

            # Substitute inventory netting if primary item is in shortage
            if initial_shortage > 0 and item_id in effective_sub_rules:
                sub_item_id, sub_ratio_bps = effective_sub_rules[item_id]
                sub_on_hand = on_hand_pool.get(sub_item_id, 0)
                if sub_on_hand > 0 and sub_ratio_bps > 0:
                    sub_needed = (initial_shortage * sub_ratio_bps + BPS_DENOMINATOR - 1) // BPS_DENOMINATOR
                    sub_used = min(sub_on_hand, sub_needed)
                    primary_covered = (sub_used * BPS_DENOMINATOR) // sub_ratio_bps
                    primary_covered = min(primary_covered, initial_shortage)
                    shortage = initial_shortage - primary_covered
                    on_hand_pool[sub_item_id] = sub_on_hand - sub_used
                else:
                    shortage = initial_shortage
            else:
                shortage = initial_shortage

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
                    on_hand=inventory_on_hand.get(item_id, 0),
                    scheduled_receipts=on_order,
                    net_shortage=shortage,
                    planned_order_quantity=planned_qty,
                )
            )

        return net_results
 
 
__all__ = [
    "BPS_DENOMINATOR",
    "MAX_BOM_DEPTH",
    "BOMComponentLine",
    "BOMExplosionEngine",
    "BOMStatus",
    "BillOfMaterials",
    "ExplodedRequirement",
    "ItemType",
    "MRPShortageRequisition",
    "NetMRPRequirement",
    "generate_mrp_shortage_requisitions",
]
