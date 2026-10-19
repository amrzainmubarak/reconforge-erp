"""Master Production Scheduling (MPS), Available-to-Promise (ATP), and Shortage Sourcing Optimization.

Zero floating-point arithmetic.
All quantities are represented as scaled integers (QuantityScaled, e.g. 1 unit = 1000 scaled units).
Monetary values are represented in integer minor units (MinorMoney).
Strict invariants:
1. Projected Inventory[t] == Projected Inventory[t-1] + Scheduled Receipts[t] + Planned Production[t] - Net Demand[t].
2. Forecast Consumption: Net Demand == max(Sales Orders, Forecast).
3. Available to Promise (ATP) strictly non-negative commitment accounting.
4. Shortage Requisition Generation is strictly idempotent without duplicate supply creation.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any, NoReturn

from reconforge.domain.finance_posting import FinancePostingError

MPS_CONTRACT_VERSION = "master-production-schedule-v1"
MAX_BUCKETS = 104
MAX_QUANTITY = 9_000_000_000_000_000_000
MAX_PRICE_MINOR = 9_000_000_000_000_000_000

_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class MPSError(FinancePostingError):
    """Domain exception for master production scheduling invariants."""


def fail(message: str, code: str = "mps_invariant_violation") -> NoReturn:
    raise MPSError(code, message)


def validate_id(val: object, name: str) -> str:
    if not isinstance(val, str) or not _ID_PATTERN.match(val):
        fail(f"Invalid canonical identifier for {name}: {val!r}")
    return val


def validate_date(val: object, name: str) -> str:
    if not isinstance(val, str) or not _DATE_PATTERN.match(val):
        fail(f"Invalid date format for {name} (expected YYYY-MM-DD): {val!r}")
    return val


def exact_int(val: object, name: str, *, allow_negative: bool = False) -> int:
    if type(val) is not int:
        fail(f"{name} must be an integer, got {type(val).__name__}")
    if not allow_negative and val < 0:
        fail(f"{name} cannot be negative: {val}")
    if abs(val) > MAX_QUANTITY:
        fail(f"{name} exceeds maximum capacity limit: {val}")
    return val


def digest_payload(data: Mapping[str, Any]) -> str:
    serialized = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class MPSBucketDemand:
    bucket_index: int
    bucket_start_date: str
    bucket_end_date: str
    sales_orders_scaled: int
    forecast_demand_scaled: int
    scheduled_receipts_scaled: int

    def validate(self) -> None:
        exact_int(self.bucket_index, "bucket_index")
        validate_date(self.bucket_start_date, "bucket_start_date")
        validate_date(self.bucket_end_date, "bucket_end_date")
        exact_int(self.sales_orders_scaled, "sales_orders_scaled")
        exact_int(self.forecast_demand_scaled, "forecast_demand_scaled")
        exact_int(self.scheduled_receipts_scaled, "scheduled_receipts_scaled")


@dataclass(frozen=True)
class MPSCalculationRow:
    bucket_index: int
    bucket_start_date: str
    bucket_end_date: str
    sales_orders_scaled: int
    forecast_demand_scaled: int
    net_demand_scaled: int
    scheduled_receipts_scaled: int
    planned_production_scaled: int
    projected_inventory_scaled: int
    available_to_promise_scaled: int
    shortage_scaled: int


@dataclass(frozen=True)
class SourcingPurchaseRequisition:
    requisition_id: str
    plan_id: str
    plan_revision: str
    item_id: str
    bucket_index: int
    required_date: str
    shortage_quantity_scaled: int
    order_quantity_scaled: int
    preferred_supplier_id: str
    unit_price_ceiling_minor: int
    currency: str
    requisition_digest: str


@dataclass(frozen=True)
class MPSPlanResult:
    plan_id: str
    plan_name: str
    revision: str
    item_id: str
    unit_of_measure: str
    quantity_scale: int
    safety_stock_scaled: int
    lot_size_multiple_scaled: int
    opening_inventory_scaled: int
    schedule_rows: list[MPSCalculationRow]
    sourcing_requisitions: list[SourcingPurchaseRequisition]
    plan_digest: str


def compute_master_production_schedule(
    *,
    plan_id: str,
    plan_name: str,
    revision: str,
    item_id: str,
    unit_of_measure: str,
    quantity_scale: int = 1000,
    safety_stock_scaled: int,
    lot_size_multiple_scaled: int = 1000,
    opening_inventory_scaled: int,
    buckets: Sequence[MPSBucketDemand],
    preferred_supplier_id: str = "SUP_DEFAULT",
    unit_price_ceiling_minor: int = 10_000,
    currency: str = "USD",
) -> MPSPlanResult:
    """Compute deterministic MPS schedule, ATP, and idempotent shortage procurement requisitions."""
    validate_id(plan_id, "plan_id")
    validate_id(item_id, "item_id")
    validate_id(preferred_supplier_id, "preferred_supplier_id")
    exact_int(safety_stock_scaled, "safety_stock_scaled")
    exact_int(opening_inventory_scaled, "opening_inventory_scaled")
    exact_int(lot_size_multiple_scaled, "lot_size_multiple_scaled")
    if lot_size_multiple_scaled <= 0:
        fail("Lot size multiple must be strictly positive.")

    if not (1 <= len(buckets) <= MAX_BUCKETS):
        fail(f"MPS requires between 1 and {MAX_BUCKETS} time buckets.")

    # Sort and validate buckets
    sorted_buckets = sorted(buckets, key=lambda b: b.bucket_index)
    for idx, b in enumerate(sorted_buckets):
        b.validate()
        if b.bucket_index != idx:
            fail(f"Bucket indices must be contiguous starting at 0, expected {idx} got {b.bucket_index}")

    current_inventory = opening_inventory_scaled
    rows: list[MPSCalculationRow] = []
    requisitions: list[SourcingPurchaseRequisition] = []

    # First pass: calculate Net Demand, Planned Production, Projected Inventory, Shortages
    preliminary_rows: list[dict[str, Any]] = []

    for b in sorted_buckets:
        # Forecast Consumption Rule: Net Demand = max(Sales Orders, Forecast)
        net_demand = max(b.sales_orders_scaled, b.forecast_demand_scaled)

        # Inventory before new production in this bucket
        inventory_before_mps = current_inventory + b.scheduled_receipts_scaled - net_demand

        planned_production = 0
        shortage = 0

        if inventory_before_mps < safety_stock_scaled:
            deficit = safety_stock_scaled - inventory_before_mps
            shortage = deficit
            # Apply lot size multiple (integer ceiling division)
            multiplier = (deficit + lot_size_multiple_scaled - 1) // lot_size_multiple_scaled
            planned_production = multiplier * lot_size_multiple_scaled

        # Final projected inventory for bucket t
        projected_inventory = inventory_before_mps + planned_production
        current_inventory = projected_inventory

        preliminary_rows.append({
            "bucket": b,
            "net_demand": net_demand,
            "planned_production": planned_production,
            "projected_inventory": projected_inventory,
            "shortage": shortage,
        })

    # Second pass: compute Available To Promise (ATP)
    # ATP in bucket t = (Opening Inventory if t=0 else 0) + Scheduled Receipts[t] + Planned Production[t]
    #                   - (Sales Orders in t up to but not including the next bucket with planned supply)
    for i, p_row in enumerate(preliminary_rows):
        b = p_row["bucket"]
        supply_in_bucket = p_row["planned_production"] + b.scheduled_receipts_scaled
        if i == 0:
            supply_in_bucket += opening_inventory_scaled

        # Find committed sales orders until next supply bucket
        committed_sales_orders = b.sales_orders_scaled
        for j in range(i + 1, len(preliminary_rows)):
            next_p = preliminary_rows[j]
            next_b = next_p["bucket"]
            next_supply = next_p["planned_production"] + next_b.scheduled_receipts_scaled
            if next_supply > 0:
                # Next replenishment bucket reached, stop looking ahead
                break
            committed_sales_orders += next_b.sales_orders_scaled

        atp = max(0, supply_in_bucket - committed_sales_orders)

        calc_row = MPSCalculationRow(
            bucket_index=b.bucket_index,
            bucket_start_date=b.bucket_start_date,
            bucket_end_date=b.bucket_end_date,
            sales_orders_scaled=b.sales_orders_scaled,
            forecast_demand_scaled=b.forecast_demand_scaled,
            net_demand_scaled=p_row["net_demand"],
            scheduled_receipts_scaled=b.scheduled_receipts_scaled,
            planned_production_scaled=p_row["planned_production"],
            projected_inventory_scaled=p_row["projected_inventory"],
            available_to_promise_scaled=atp,
            shortage_scaled=p_row["shortage"],
        )
        rows.append(calc_row)

        # If shortage occurred, create an idempotent sourcing purchase requisition
        if p_row["shortage"] > 0:
            req_data = {
                "plan_id": plan_id,
                "plan_revision": revision,
                "item_id": item_id,
                "bucket_index": b.bucket_index,
                "required_date": b.bucket_start_date,
                "shortage_quantity_scaled": p_row["shortage"],
                "order_quantity_scaled": p_row["planned_production"],
                "preferred_supplier_id": preferred_supplier_id,
                "unit_price_ceiling_minor": unit_price_ceiling_minor,
                "currency": currency,
            }
            req_digest = digest_payload(req_data)
            req_id = f"PR-{plan_id}-B{b.bucket_index}-{req_digest[:8]}"

            requisitions.append(
                SourcingPurchaseRequisition(
                    requisition_id=req_id,
                    plan_id=plan_id,
                    plan_revision=revision,
                    item_id=item_id,
                    bucket_index=b.bucket_index,
                    required_date=b.bucket_start_date,
                    shortage_quantity_scaled=p_row["shortage"],
                    order_quantity_scaled=p_row["planned_production"],
                    preferred_supplier_id=preferred_supplier_id,
                    unit_price_ceiling_minor=unit_price_ceiling_minor,
                    currency=currency,
                    requisition_digest=req_digest,
                )
            )

    plan_payload = {
        "contract_version": MPS_CONTRACT_VERSION,
        "plan_id": plan_id,
        "plan_name": plan_name,
        "revision": revision,
        "item_id": item_id,
        "unit_of_measure": unit_of_measure,
        "quantity_scale": quantity_scale,
        "safety_stock_scaled": safety_stock_scaled,
        "lot_size_multiple_scaled": lot_size_multiple_scaled,
        "opening_inventory_scaled": opening_inventory_scaled,
        "schedule_rows": [asdict(r) for r in rows],
        "sourcing_requisitions": [asdict(req) for req in requisitions],
    }
    plan_digest = digest_payload(plan_payload)

    return MPSPlanResult(
        plan_id=plan_id,
        plan_name=plan_name,
        revision=revision,
        item_id=item_id,
        unit_of_measure=unit_of_measure,
        quantity_scale=quantity_scale,
        safety_stock_scaled=safety_stock_scaled,
        lot_size_multiple_scaled=lot_size_multiple_scaled,
        opening_inventory_scaled=opening_inventory_scaled,
        schedule_rows=rows,
        sourcing_requisitions=requisitions,
        plan_digest=plan_digest,
    )
