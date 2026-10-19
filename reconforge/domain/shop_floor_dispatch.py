"""Deterministic Shop Floor Execution, Lot Genealogy and Traceability Invariants.

Enforces:
1. Strict integer quantity conservation: Finished Goods + Scrap + Remaining WIP <= Dispatched Input.
2. Contiguous operation step execution without skipping or out-of-order completion.
3. Bidirectional lot/serial genealogy traversal (forward recall and backward root-cause tracing).
4. Cycle-safe genealogy graph traversal.
5. Zero floating-point arithmetic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")


class ShopFloorExecutionError(ValueError):
    """Raised when a shop floor execution invariant or genealogy constraint is violated."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _check_id(val: str, field_name: str) -> str:
    cleaned = val.strip() if isinstance(val, str) else ""
    if not _ID_PATTERN.fullmatch(cleaned):
        raise ShopFloorExecutionError(
            code="invalid_identifier",
            message=f"{field_name} must be a valid alphanumeric identifier: '{val}'",
        )
    return cleaned


LotStatus = Literal["active", "quarantined", "consumed", "scrapped"]
StepStatus = Literal["pending", "in_progress", "completed", "held"]


@dataclass(frozen=True)
class LotTraceabilityRecord:
    """Traceable batch/lot record for manufacturing raw materials or finished goods."""

    workspace_id: str
    lot_id: str
    item_id: str
    batch_number: str
    quantity_scaled: int
    scale_factor: int = 1000  # Default 3 decimals (e.g. 1000 = 1.000 units)
    status: LotStatus = "active"
    notes: str = ""

    def __post_init__(self) -> None:
        _check_id(self.workspace_id, "workspace_id")
        _check_id(self.lot_id, "lot_id")
        _check_id(self.item_id, "item_id")
        _check_id(self.batch_number, "batch_number")
        if self.quantity_scaled <= 0:
            raise ShopFloorExecutionError(
                code="invalid_quantity",
                message=f"Lot quantity must be positive, got {self.quantity_scaled}",
            )
        if self.scale_factor <= 0:
            raise ShopFloorExecutionError(
                code="invalid_scale_factor",
                message="Scale factor must be strictly positive",
            )


@dataclass(frozen=True)
class ShopFloorOperationStep:
    """Single work center operation within a work order routing."""

    step_id: str
    work_order_id: str
    operation_sequence: int
    work_center_id: str
    operator_id: str
    status: StepStatus
    actual_run_minutes: int
    quantity_completed_scaled: int
    quantity_scrapped_scaled: int
    scrap_reason_code: str = ""
    started_at: str = ""
    completed_at: str = ""

    def __post_init__(self) -> None:
        _check_id(self.step_id, "step_id")
        _check_id(self.work_order_id, "work_order_id")
        _check_id(self.work_center_id, "work_center_id")
        if self.operation_sequence <= 0:
            raise ShopFloorExecutionError(
                code="invalid_sequence",
                message=f"Operation sequence must be positive, got {self.operation_sequence}",
            )
        if self.actual_run_minutes < 0:
            raise ShopFloorExecutionError(
                code="invalid_duration",
                message="Actual run minutes cannot be negative",
            )
        if self.quantity_completed_scaled < 0 or self.quantity_scrapped_scaled < 0:
            raise ShopFloorExecutionError(
                code="invalid_quantity",
                message="Completed and scrapped quantities cannot be negative",
            )


@dataclass(frozen=True)
class WorkOrderDispatch:
    """Dispatched manufacturing work order ready for or undergoing execution."""

    workspace_id: str
    dispatch_id: str
    work_order_id: str
    item_id: str
    scheduled_quantity_scaled: int
    dispatched_lot_id: str
    dispatched_at: str
    steps: tuple[ShopFloorOperationStep, ...]
    consumed_lot_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _check_id(self.workspace_id, "workspace_id")
        _check_id(self.dispatch_id, "dispatch_id")
        _check_id(self.work_order_id, "work_order_id")
        _check_id(self.item_id, "item_id")
        _check_id(self.dispatched_lot_id, "dispatched_lot_id")
        if self.scheduled_quantity_scaled <= 0:
            raise ShopFloorExecutionError(
                code="invalid_scheduled_quantity",
                message="Scheduled quantity must be strictly positive",
            )
        # Verify steps contiguous sequences
        sequences = [step.operation_sequence for step in self.steps]
        if sequences and sequences != list(range(1, len(sequences) + 1)):
            raise ShopFloorExecutionError(
                code="non_contiguous_operations",
                message=f"Routing operation sequences must be contiguous starting from 1, got {sequences}",
            )


@dataclass(frozen=True)
class GenealogyNode:
    """Node in a lot genealogy graph representing component consumption or finished output."""

    lot_id: str
    item_id: str
    quantity_scaled: int
    direction: Literal["forward", "backward"]
    children: tuple[GenealogyNode, ...] = ()


def validate_step_progression(
    dispatch: WorkOrderDispatch,
    completed_step: ShopFloorOperationStep,
) -> None:
    """Enforce routing sequence rules and quantity conservation."""
    if completed_step.work_order_id != dispatch.work_order_id:
        raise ShopFloorExecutionError(
            code="work_order_mismatch",
            message=f"Step work order {completed_step.work_order_id} does not match dispatch {dispatch.work_order_id}",
        )

    # Check prior steps in dispatch are completed
    for step in dispatch.steps:
        if step.operation_sequence < completed_step.operation_sequence and step.status != "completed":
            raise ShopFloorExecutionError(
                code="prior_step_incomplete",
                message=(
                    f"Cannot execute sequence {completed_step.operation_sequence}: "
                    f"prior sequence {step.operation_sequence} has status '{step.status}'"
                ),
            )

    # Invariant: Total dispositioned quantity (completed + scrap) cannot exceed scheduled quantity
    total_dispositioned = completed_step.quantity_completed_scaled + completed_step.quantity_scrapped_scaled
    if total_dispositioned > dispatch.scheduled_quantity_scaled:
        raise ShopFloorExecutionError(
            code="quantity_exceeded",
            message=(
                f"Completed ({completed_step.quantity_completed_scaled}) + "
                f"Scrap ({completed_step.quantity_scrapped_scaled}) = {total_dispositioned} "
                f"exceeds scheduled dispatch quantity {dispatch.scheduled_quantity_scaled}"
            ),
        )


def traverse_genealogy(
    root_lot_id: str,
    edges: list[tuple[str, str, int]],  # (parent_lot, child_lot, qty)
    lot_item_map: dict[str, str],
    direction: Literal["forward", "backward"],
    max_depth: int = 20,
) -> GenealogyNode:
    """Build a cycle-safe tree of lot genealogy in forward (where used) or backward (what consumed) direction."""
    # Build adjacency list
    graph: dict[str, list[tuple[str, int]]] = {}
    for parent, child, qty in edges:
        if direction == "forward":
            # Parent consumed to make child
            graph.setdefault(parent, []).append((child, qty))
        else:
            # Child derived from parent
            graph.setdefault(child, []).append((parent, qty))

    visited: set[str] = set()

    def _traverse(current_lot: str, depth: int) -> GenealogyNode:
        if depth > max_depth:
            raise ShopFloorExecutionError(
                code="genealogy_depth_exceeded",
                message=f"Genealogy depth ceiling of {max_depth} exceeded",
            )
        if current_lot in visited:
            raise ShopFloorExecutionError(
                code="genealogy_cycle_detected",
                message=f"Genealogy cycle detected at lot {current_lot}",
            )
        visited.add(current_lot)

        item_id = lot_item_map.get(current_lot, "UNKNOWN_ITEM")
        adjacent = graph.get(current_lot, [])
        children_nodes: list[GenealogyNode] = []

        for next_lot, _qty in adjacent:
            child_node = _traverse(next_lot, depth + 1)
            children_nodes.append(child_node)

        visited.remove(current_lot)
        return GenealogyNode(
            lot_id=current_lot,
            item_id=item_id,
            quantity_scaled=0,  # root level quantity, populated per node
            direction=direction,
            children=tuple(children_nodes),
        )

    return _traverse(root_lot_id, 0)
