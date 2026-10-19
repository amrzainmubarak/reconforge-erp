"""Comprehensive tests for Quality Inspection Plans, NCRs, Rework Orders, and Quality API routes."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reconforge.api.errors import APIError, api_error_handler
from reconforge.api.routes.manufacturing_quality import (
    require_quality_manage,
    require_quality_read,
    router,
)
from reconforge.auth.models import LocalUser
from reconforge.domain.manufacturing_quality_rework import (
    NonConformanceReport,
    QualityInspectionPlan,
    QualityReworkError,
    QualitySpecification,
    ReworkOrder,
    ReworkRoutingStep,
)


def test_quality_specification_validation() -> None:
    spec = QualitySpecification(
        param_name="shaft_outer_diameter_microns",
        target_value=25_000,
        tolerance_lower=24_980,
        tolerance_upper=25_020,
        unit_of_measure="um",
        is_critical=True,
    )
    assert spec.is_conforming(25_000)
    assert spec.is_conforming(24_980)
    assert spec.is_conforming(25_020)
    assert not spec.is_conforming(24_979)
    assert not spec.is_conforming(25_021)

    from reconforge.domain.finance_posting import FinancePostingError

    # Inverted lower/upper tolerance rejected
    with pytest.raises(FinancePostingError):
        QualitySpecification(
            param_name="invalid_spec",
            target_value=100,
            tolerance_lower=120,
            tolerance_upper=150,
        )


def test_quality_inspection_plan_evaluation() -> None:
    specs = (
        QualitySpecification(param_name="hardness_hrc", target_value=55, tolerance_lower=52, tolerance_upper=58),
        QualitySpecification(param_name="surface_finish_ra", target_value=8, tolerance_lower=0, tolerance_upper=12),
    )
    plan = QualityInspectionPlan(
        plan_id="QIP-GEAR-01",
        item_id="ITEM-GEAR",
        revision="A.1",
        name="Gear Hobbing Inspection",
        sample_size_units=5,
        specifications=specs,
    )

    # Conforming measurements
    passed, defects = plan.evaluate_measurements({"hardness_hrc": 54, "surface_finish_ra": 10})
    assert passed
    assert len(defects) == 0

    # Non-conforming measurements
    passed2, defects2 = plan.evaluate_measurements({"hardness_hrc": 50, "surface_finish_ra": 15})
    assert not passed2
    assert len(defects2) == 2


def test_ncr_lifecycle_and_disposition() -> None:
    ncr = NonConformanceReport(
        ncr_id="NCR-2026-001",
        lot_id="LOT-GEAR-88",
        work_order_id="WO-M-500",
        defect_code="DEF_UNDER_HARDNESS",
        defect_severity="major",
        inspector_id="insp_dan",
        quarantined_quantity_scaled=50_000,
    )
    assert ncr.status == "open"
    assert ncr.disposition is None

    # Disposition to rework
    dispositioned = ncr.disposition_ncr(
        disposition="rework",
        notes="Re-heat treat in vacuum furnace and re-temper at 350C",
        actor="metallurgist_sue",
    )
    assert dispositioned.status == "dispositioned"
    assert dispositioned.disposition == "rework"
    assert dispositioned.disposition_by == "metallurgist_sue"

    # Cannot re-disposition
    with pytest.raises(QualityReworkError, match="cannot be dispositioned"):
        dispositioned.disposition_ncr(disposition="scrap", notes="too late", actor="bob")

    # Close NCR
    closed = dispositioned.close_ncr(actor="qa_manager")
    assert closed.status == "closed"


def test_rework_order_cost_accumulation() -> None:
    step1 = ReworkRoutingStep(
        step_number=1,
        work_center_id="WC-FURNACE-01",
        operation_description="Secondary Austenitizing & Quench",
        estimated_minutes=120,
    )
    step2 = ReworkRoutingStep(
        step_number=2,
        work_center_id="WC-INSPECT-01",
        operation_description="Rockwell Hardness Re-test",
        estimated_minutes=30,
    )
    rework = ReworkOrder(
        rework_order_id="RWO-001",
        parent_work_order_id="WO-M-500",
        ncr_id="NCR-2026-001",
        item_id="ITEM-GEAR",
        rework_quantity_scaled=50_000,
        rework_routing_steps=(step1, step2),
        rework_cost_center="CC_REWORK_HEAT",
    )
    assert rework.status == "draft"

    released = rework.release()
    assert released.status == "released"

    # Log step 1: 90 actual minutes @ 60,000 minor units/hr ($60.00/hr)
    # Exact cost: (90 * 60,000 + 30) // 60 = 5,400,030 // 60 = 90,000 minor units ($90.00)
    in_prog = released.log_rework_step(
        step_number=1,
        actual_minutes=90,
        labor_rate_hourly_minor=60_000,
    )
    assert in_prog.status == "in_progress"
    assert in_prog.accumulated_rework_cost_minor == 90_000

    # Log step 2: 30 actual minutes @ 40,000 minor units/hr ($40.00/hr)
    # Exact cost: (30 * 40,000 + 30) // 60 = 1,200,030 // 60 = 20,000 minor units ($20.00)
    # Total accumulated: 90,000 + 20,000 = 110,000 minor units ($110.00)
    in_prog2 = in_prog.log_rework_step(
        step_number=2,
        actual_minutes=30,
        labor_rate_hourly_minor=40_000,
    )
    assert in_prog2.accumulated_rework_cost_minor == 110_000

    # Complete rework order
    completed = in_prog2.complete(actor="supervisor_dave")
    assert completed.status == "completed"
    assert completed.completed_at is not None


def test_quality_api_routes(tmp_path: object) -> None:
    db_path = str(Path(str(tmp_path)) / "quality_api_test.db")
    app = FastAPI()
    app.add_exception_handler(APIError, cast(Any, api_error_handler))
    app.include_router(router, prefix="/api/v1")
    app.state.db_path = db_path
    app.state.server_mode = False

    user = LocalUser(id="qa_tester", username="qa_lead", display_name="QA Lead")
    app.dependency_overrides[require_quality_read] = lambda: user
    app.dependency_overrides[require_quality_manage] = lambda: user

    client = TestClient(app)

    # 1. Register inspection plan
    plan_payload = {
        "plan_id": "QIP-TURBINE-01",
        "item_id": "TURBINE-BLADE-01",
        "revision": "B.2",
        "name": "Turbine Blade Quality Plan",
        "sample_size_units": 10,
        "specifications": [
            {
                "param_name": "blade_thickness_microns",
                "target_value": 3000,
                "tolerance_lower": 2950,
                "tolerance_upper": 3050,
                "unit_of_measure": "um",
                "is_critical": True,
            }
        ],
    }
    resp = client.post("/api/v1/manufacturing/quality/inspection-plans", json=plan_payload)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "registered"

    # 2. Get inspection plan
    resp_get = client.get("/api/v1/manufacturing/quality/inspection-plans/TURBINE-BLADE-01")
    assert resp_get.status_code == 200
    assert resp_get.json()["plan_id"] == "QIP-TURBINE-01"

    # 3. Evaluate measurements
    resp_eval = client.post(
        "/api/v1/manufacturing/quality/evaluate",
        json={"item_id": "TURBINE-BLADE-01", "measurements": {"blade_thickness_microns": 2900}},
    )
    assert resp_eval.status_code == 200
    assert resp_eval.json()["is_passed"] is False
    assert resp_eval.json()["status"] == "rejected"

    # 4. Create NCR
    ncr_payload = {
        "ncr_id": "NCR-2026-TURBINE-01",
        "lot_id": "LOT-TB-99",
        "work_order_id": "WO-TB-100",
        "defect_code": "DEF_UNDER_THICKNESS",
        "defect_severity": "critical",
        "inspector_id": "qa_lead",
        "quarantined_quantity_scaled": 10_000,
    }
    resp_ncr = client.post("/api/v1/manufacturing/quality/ncrs", json=ncr_payload)
    assert resp_ncr.status_code == 200
    assert resp_ncr.json()["status"] == "quarantined"

    # 5. Disposition NCR
    resp_disp = client.post(
        "/api/v1/manufacturing/quality/ncrs/NCR-2026-TURBINE-01/disposition",
        json={"disposition": "rework", "notes": "Plasma spray coating to build thickness"},
    )
    assert resp_disp.status_code == 200
    assert resp_disp.json()["status"] == "dispositioned"

    # 6. Create Rework Order
    rework_payload = {
        "rework_order_id": "RWO-TB-01",
        "parent_work_order_id": "WO-TB-100",
        "ncr_id": "NCR-2026-TURBINE-01",
        "item_id": "TURBINE-BLADE-01",
        "rework_quantity_scaled": 10_000,
        "rework_cost_center": "CC_PLASMA_SPRAY",
        "rework_routing_steps": [
            {
                "step_number": 1,
                "work_center_id": "WC-PLASMA-01",
                "operation_description": "Thermal Spray Build-up",
                "estimated_minutes": 60,
                "labor_rate_hourly_minor": 80_000,
            }
        ],
    }
    resp_rwo = client.post("/api/v1/manufacturing/quality/rework-orders", json=rework_payload)
    assert resp_rwo.status_code == 200
    assert resp_rwo.json()["status"] == "released"

    # 7. Log rework step
    resp_step = client.post(
        "/api/v1/manufacturing/quality/rework-orders/RWO-TB-01/log-step",
        json={"step_number": 1, "actual_minutes": 60, "labor_rate_hourly_minor": 80_000},
    )
    assert resp_step.status_code == 200
    # 60 min @ $80/hr = $80.00 (80_000 minor)
    assert resp_step.json()["accumulated_rework_cost_minor"] == 80_000

    # 8. Complete rework order
    resp_comp = client.post("/api/v1/manufacturing/quality/rework-orders/RWO-TB-01/complete")
    assert resp_comp.status_code == 200
    assert resp_comp.json()["status"] == "completed"
    assert resp_comp.json()["total_rework_cost_minor"] == 80_000


def test_quality_api_server_mode_fail_closed() -> None:
    app = FastAPI()
    app.add_exception_handler(APIError, cast(Any, api_error_handler))
    app.include_router(router, prefix="/api/v1")
    app.state.server_mode = True

    user = LocalUser(id="qa_tester", username="qa_lead", display_name="QA Lead")
    app.dependency_overrides[require_quality_read] = lambda: user

    client = TestClient(app)
    resp = client.get("/api/v1/manufacturing/quality/inspection-plans/ANY-ITEM")
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "server_postgres_unavailable"
