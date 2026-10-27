"""Tests for Master Production Scheduling (MPS) API schemas and SQLite repository."""

from __future__ import annotations

import sqlite3

import pytest
from pydantic import ValidationError

from reconforge.api.routes.master_production_schedule import (
    MPSBucketDemandInput,
)
from reconforge.domain.master_production_schedule import (
    MPSBucketDemand,
    compute_master_production_schedule,
)
from reconforge.infrastructure.sqlite_mps import SQLiteMPSRepository


def test_mps_api_schemas_validation() -> None:
    valid_bucket = {
        "bucket_index": 0,
        "bucket_start_date": "2026-05-01",
        "bucket_end_date": "2026-05-07",
        "sales_orders_scaled": 10_000,
        "forecast_demand_scaled": 12_000,
        "scheduled_receipts_scaled": 0,
    }
    b_input = MPSBucketDemandInput.model_validate(valid_bucket)
    domain_b = b_input.to_domain()
    assert domain_b.bucket_index == 0
    assert domain_b.sales_orders_scaled == 10_000

    # Negative bucket index fails
    with pytest.raises(ValidationError):
        MPSBucketDemandInput.model_validate({**valid_bucket, "bucket_index": -1})

    # Invalid date format fails
    with pytest.raises(ValidationError):
        MPSBucketDemandInput.model_validate({**valid_bucket, "bucket_start_date": "05/01/2026"})


def test_sqlite_mps_repository_lifecycle() -> None:
    conn = sqlite3.connect(":memory:")
    repo = SQLiteMPSRepository(conn)

    buckets = [
        MPSBucketDemand(0, "2026-05-01", "2026-05-07", 20_000, 25_000, 0),
        MPSBucketDemand(1, "2026-05-08", "2026-05-14", 15_000, 15_000, 0),
    ]

    plan_result = compute_master_production_schedule(
        plan_id="MPS_SQLITE_TEST",
        plan_name="SQLite Test Plan",
        revision="1.0.0",
        item_id="ITEM_FG_100",
        unit_of_measure="EA",
        safety_stock_scaled=10_000,
        lot_size_multiple_scaled=5_000,
        opening_inventory_scaled=20_000,
        buckets=buckets,
        preferred_supplier_id="SUPP_ALPHA",
        unit_price_ceiling_minor=25_000,
    )

    rec_id = repo.save_plan(
        workspace_id="ws-mfg-test",
        plan_result=plan_result,
        created_by="planner_dan",
    )
    assert rec_id == "mps_MPS_SQLITE_TEST_1.0.0"

    # Get plan
    plan_data = repo.get_plan(workspace_id="ws-mfg-test", plan_id="MPS_SQLITE_TEST", revision="1.0.0")
    assert plan_data is not None
    assert plan_data["plan_name"] == "SQLite Test Plan"
    assert len(plan_data["plan"]["schedule_rows"]) == 2

    # List plans
    plans = repo.list_plans(workspace_id="ws-mfg-test")
    assert len(plans) == 1
    assert plans[0]["plan_id"] == "MPS_SQLITE_TEST"

    # List requisitions
    reqs = repo.list_requisitions(workspace_id="ws-mfg-test", plan_id="MPS_SQLITE_TEST")
    assert len(reqs) > 0
    assert reqs[0]["preferred_supplier_id"] == "SUPP_ALPHA"
