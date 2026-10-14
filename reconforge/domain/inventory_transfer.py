"""Exact same-entity stock transfer ownership over the existing native ledger."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from reconforge.domain.finance_posting import FinancePostingError, text
from reconforge.domain.inventory_receipt_posting import exact_date
from reconforge.domain.manufacturing_execution import exact_integer
from reconforge.platform.inventory_values import quantity_to_scaled, scaled_to_text

SCHEMA_VERSION = "inventory-transfer-v1"
ACK_SCHEMA_VERSION = "inventory-transfer-command-ack-v1"
PHASES = ("Draft", "Reviewed", "Posted", "Cancelled")
MAX_COST_SOURCES = 32
READ = frozenset({"inventory_transfer.read", "inventory.read", "inventory.valuation.read", "finance_core.read"})
PERMISSIONS = {
    "read": READ,
    "create": READ | {"inventory_transfer.manage", "inventory.manage"},
    "inverse-create": READ | {"inventory_transfer.manage", "inventory.manage"},
    "review": READ | {"inventory_transfer.approve", "inventory.manage"},
    "post": READ | {"inventory_transfer.post", "inventory.post"},
    "cancel": READ | {"inventory_transfer.approve", "inventory.manage"},
}


def fail(message: str, code: str = "inventory_transfer_invalid") -> None:
    raise FinancePostingError(code, message)


def exact_scope(value: Mapping[str, Any]) -> dict[str, str]:
    keys = {"workspace_id", "organization_id", "legal_entity_id"}
    if not isinstance(value, Mapping) or set(value) != keys:
        fail("Transfer scope requires its exact workspace, organization and legal entity.")
    return {key: text(value[key], key) for key in sorted(keys)}


@dataclass(frozen=True)
class TransferPreparation:
    number: str
    item_code: str
    quantity: str
    from_location: str
    to_location: str
    period_id: str
    posting_date: str
    reason: str
    scope: Mapping[str, Any]

    def payload(self) -> dict[str, Any]:
        if not isinstance(self.quantity, str):
            fail("Transfer quantity must be exact decimal text in the native base unit.")
        locations = [text(value, "location", maximum=129) for value in (self.from_location, self.to_location)]
        if any(len(value.split("/")) != 2 or any(not part for part in value.split("/")) for value in locations):
            fail("Transfer locations require exact WAREHOUSE/LOCATION references.")
        if locations[0] == locations[1] or locations[0].split("/")[0] == locations[1].split("/")[0]:
            fail("This transfer requires two distinct warehouses.")
        # Validate syntax/bounds here; the approved master supplies actual precision.
        quantity_to_scaled(self.quantity, 6, "Transfer quantity")
        return {"schema_version": SCHEMA_VERSION, "number": text(self.number, "number", maximum=64),
            "item_code": text(self.item_code, "item_code", maximum=64), "quantity": self.quantity,
            "from_location": locations[0], "to_location": locations[1], "period_id": text(self.period_id, "period_id"),
            "posting_date": exact_date(self.posting_date), "reason": text(self.reason, "reason", maximum=500),
            "scope": exact_scope(self.scope)}


@dataclass(frozen=True)
class TransferInversePreparation:
    original_id: str
    expected_digest: str
    expected_version: int
    number: str
    period_id: str
    posting_date: str
    reason: str

    def payload(self) -> dict[str, Any]:
        return {"original_id": text(self.original_id, "original_id"),
            "expected_digest": text(self.expected_digest, "expected_digest", maximum=64),
            "expected_version": exact_integer(self.expected_version, positive=True), "number": text(self.number, "number", maximum=64),
            "period_id": text(self.period_id, "period_id"), "posting_date": exact_date(self.posting_date),
            "reason": text(self.reason, "reason", maximum=500)}


def exact_quantity(value: str, precision: int) -> tuple[int, str]:
    scale = exact_integer(precision)
    if scale > 6 or not isinstance(value, str):
        fail("Transfer quantity needs captured native base-unit precision.")
    scaled = quantity_to_scaled(value, scale, "Transfer quantity")
    return scaled, scaled_to_text(scaled, decimal_places=scale)


def require_transition(phase: int, operation: str, maker: str, reviewer: str | None, actor: str) -> int:
    current = exact_integer(phase)
    if operation == "review" and current == 0 and actor != maker:
        return 1
    if operation == "post" and current == 1 and reviewer is not None and actor not in {maker, reviewer}:
        return 2
    if operation == "cancel" and current in {0, 1} and actor != maker:
        return 3
    fail("Transfer phase and three distinct current humans must follow the original source.", "inventory_transfer_governance_conflict")
    return current


def require_capacity(quantity_scaled: int, physical_scaled: int, reserved_scaled: int, fifo_free_scaled: int) -> None:
    quantity = exact_integer(quantity_scaled, positive=True)
    physical, reserved, fifo = (exact_integer(value) for value in (physical_scaled, reserved_scaled, fifo_free_scaled))
    if reserved > physical or quantity > physical - reserved or quantity > fifo:
        fail("Transfer needs currently unreserved physical stock and approved entity FIFO backing.", "inventory_transfer_capacity_conflict")


def exposed_minor(snapshot: Mapping[str, Any]) -> int:
    """Authorize complete cited values, never only a selected transfer portion."""
    value = exact_integer(snapshot["remaining_value_minor"])
    sources = snapshot["sources"]
    if not isinstance(sources, list) or not 1 <= len(sources) <= MAX_COST_SOURCES:
        fail("A bounded complete original approved cost-source population is required.")
    for source in sources:
        for amount in source["exposed_amounts_minor"]:
            value = max(value, exact_integer(amount))
    return value
