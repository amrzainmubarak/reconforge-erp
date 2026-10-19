"""Unit tests for Master Production Scheduling (MPS) domain model, ATP calculation, and sourcing."""

import pytest

from reconforge.domain.master_production_schedule import (
    MPSBucketDemand,
    MPSError,
    compute_master_production_schedule,
)


def test_mps_basic_forecast_consumption_and_conservation() -> None:
    # 4 weekly buckets
    # Opening inventory: 50,000 (scaled units, e.g. 50 EA)
    # Safety stock target: 20,000 (20 EA)
    # Lot size multiple: 10,000 (10 EA)
    buckets = [
        MPSBucketDemand(
            bucket_index=0,
            bucket_start_date="2026-05-01",
            bucket_end_date="2026-05-07",
            sales_orders_scaled=30_000,
            forecast_demand_scaled=25_000,  # Sales orders > Forecast -> Net demand = 30_000
            scheduled_receipts_scaled=0,
        ),
        MPSBucketDemand(
            bucket_index=1,
            bucket_start_date="2026-05-08",
            bucket_end_date="2026-05-14",
            sales_orders_scaled=10_000,
            forecast_demand_scaled=25_000,  # Forecast > Sales orders -> Net demand = 25_000
            scheduled_receipts_scaled=0,
        ),
        MPSBucketDemand(
            bucket_index=2,
            bucket_start_date="2026-05-15",
            bucket_end_date="2026-05-21",
            sales_orders_scaled=15_000,
            forecast_demand_scaled=15_000,
            scheduled_receipts_scaled=10_000,
        ),
        MPSBucketDemand(
            bucket_index=3,
            bucket_start_date="2026-05-22",
            bucket_end_date="2026-05-28",
            sales_orders_scaled=40_000,
            forecast_demand_scaled=30_000,
            scheduled_receipts_scaled=0,
        ),
    ]

    result = compute_master_production_schedule(
        plan_id="MPS_PLAN_01",
        plan_name="Q2 Assembly MPS",
        revision="1.0.0",
        item_id="ITEM_FG_PUMP_01",
        unit_of_measure="EA",
        quantity_scale=1000,
        safety_stock_scaled=20_000,
        lot_size_multiple_scaled=10_000,
        opening_inventory_scaled=50_000,
        buckets=buckets,
        preferred_supplier_id="SUP_ACME",
        unit_price_ceiling_minor=15_000,
        currency="USD",
    )

    assert result.plan_id == "MPS_PLAN_01"
    assert len(result.schedule_rows) == 4

    # Verify bucket 0
    row0 = result.schedule_rows[0]
    assert row0.net_demand_scaled == 30_000
    # Opening (50k) - Net Demand (30k) = 20k == Safety Stock (20k) -> No planned production needed
    assert row0.planned_production_scaled == 0
    assert row0.projected_inventory_scaled == 20_000
    assert row0.shortage_scaled == 0

    # Verify bucket 1
    row1 = result.schedule_rows[1]
    assert row1.net_demand_scaled == 25_000
    # Before MPS: 20k - 25k = -5k. Deficit to safety stock (20k) = 25k.
    # Lot size multiple 10k: ceiling(25k/10k)*10k = 30k planned production.
    assert row1.planned_production_scaled == 30_000
    # Final projected inventory: -5k + 30k = 25k.
    assert row1.projected_inventory_scaled == 25_000
    assert row1.shortage_scaled == 25_000

    # Verify Invariant 1: Conservation across all buckets
    prev_inv = result.opening_inventory_scaled
    for r in result.schedule_rows:
        expected_inv = prev_inv + r.scheduled_receipts_scaled + r.planned_production_scaled - r.net_demand_scaled
        assert r.projected_inventory_scaled == expected_inv
        prev_inv = r.projected_inventory_scaled

    # Verify Shortage Sourcing Requisitions
    # Buckets with shortages should have generated PRs
    assert len(result.sourcing_requisitions) > 0
    pr_row1 = next(pr for pr in result.sourcing_requisitions if pr.bucket_index == 1)
    assert pr_row1.shortage_quantity_scaled == 25_000
    assert pr_row1.order_quantity_scaled == 30_000
    assert pr_row1.preferred_supplier_id == "SUP_ACME"
    assert pr_row1.unit_price_ceiling_minor == 15_000


def test_mps_atp_available_to_promise() -> None:
    # Verify ATP promises uncommitted supply without violating committed sales orders
    buckets = [
        MPSBucketDemand(
            bucket_index=0,
            bucket_start_date="2026-06-01",
            bucket_end_date="2026-06-07",
            sales_orders_scaled=20_000,
            forecast_demand_scaled=20_000,
            scheduled_receipts_scaled=0,
        ),
        MPSBucketDemand(
            bucket_index=1,
            bucket_start_date="2026-06-08",
            bucket_end_date="2026-06-14",
            sales_orders_scaled=15_000,
            forecast_demand_scaled=15_000,
            scheduled_receipts_scaled=0,
        ),
    ]

    result = compute_master_production_schedule(
        plan_id="MPS_ATP_TEST",
        plan_name="ATP Verification Plan",
        revision="1.0.0",
        item_id="ITEM_FG_02",
        unit_of_measure="EA",
        safety_stock_scaled=0,
        lot_size_multiple_scaled=10_000,
        opening_inventory_scaled=100_000,
        buckets=buckets,
    )

    # In bucket 0: Supply = Opening 100k + Supply 0 = 100k.
    # No further supply arrives in bucket 1.
    # Total committed sales orders in horizon = 20k + 15k = 35k.
    # ATP in bucket 0 = 100k - 35k = 65k.
    assert result.schedule_rows[0].available_to_promise_scaled == 65_000
    # In bucket 1: Supply = 0, so ATP = 0.
    assert result.schedule_rows[1].available_to_promise_scaled == 0


def test_mps_non_contiguous_buckets_fail() -> None:
    buckets = [
        MPSBucketDemand(0, "2026-05-01", "2026-05-07", 1000, 1000, 0),
        MPSBucketDemand(2, "2026-05-15", "2026-05-21", 1000, 1000, 0),  # Skipped index 1!
    ]
    with pytest.raises(MPSError) as exc_info:
        compute_master_production_schedule(
            plan_id="MPS_FAIL",
            plan_name="Fail Plan",
            revision="1.0.0",
            item_id="ITEM_01",
            unit_of_measure="EA",
            safety_stock_scaled=0,
            opening_inventory_scaled=0,
            buckets=buckets,
        )
    assert "Bucket indices must be contiguous" in str(exc_info.value)
