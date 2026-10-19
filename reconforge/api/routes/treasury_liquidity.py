"""API routes for Treasury Cash Positions, Liquidity Flows, and Forecast Scenarios."""

from __future__ import annotations

import sqlite3
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from reconforge.api.dependencies import require_permission
from reconforge.api.errors import APIError
from reconforge.auth.models import LocalUser
from reconforge.domain.treasury_liquidity import (
    CashPosition,
    LiquidityFlow,
    StressScenario,
)
from reconforge.infrastructure.sqlite_treasury import SqliteTreasuryRepository

router = APIRouter(prefix="/treasury", tags=["treasury"])
Read = Annotated[LocalUser, Depends(require_permission("finance_core.read"))]
Manage = Annotated[LocalUser, Depends(require_permission("finance_core.manage"))]


def _repo(request: Request) -> SqliteTreasuryRepository:
    db_path = getattr(request.app.state, "db_path", None)
    if db_path is None:
        raise APIError(status_code=500, code="db_not_configured", message="API database path is not configured.")
    conn = sqlite3.connect(db_path)
    return SqliteTreasuryRepository(conn)


class PositionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    bank_account_id: str = Field(min_length=1, max_length=64)
    bank_name: str = Field(min_length=1, max_length=128)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    as_of_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    cleared_balance_minor: str = Field(pattern=r"^(0|[1-9][0-9]{0,18})$")
    minimum_covenant_minor: str = Field(default="0", pattern=r"^(0|[1-9][0-9]{0,18})$")


class FlowRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    flow_id: str = Field(min_length=1, max_length=64)
    direction: Literal["inflow", "outflow"]
    source_type: Literal["receivable", "payable", "payroll", "tax", "debt_service", "manual"]
    source_reference: str = Field(min_length=1, max_length=128)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    due_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    amount_minor: str = Field(pattern=r"^[1-9][0-9]{0,18}$")
    confidence_bps: int = Field(default=10000, ge=0, le=10000)
    status: Literal["projected", "confirmed", "disputed", "settled"] = "projected"


class ScenarioParams(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    scenario_name: str = Field(min_length=1, max_length=64)
    ar_delay_days: int = Field(default=0, ge=0, le=180)
    ar_haircut_bps: int = Field(default=0, ge=0, le=10000)
    ap_acceleration_days: int = Field(default=0, ge=0, le=180)
    unplanned_outflow_minor: str = Field(default="0", pattern=r"^(0|[1-9][0-9]{0,18})$")


class ForecastRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    bank_account_id: str = Field(min_length=1, max_length=64)
    horizon_days: int = Field(default=30, ge=1, le=365)
    bucket_days: int = Field(default=1, ge=1, le=90)
    scenario: ScenarioParams | None = None


@router.post("/positions")
def upsert_position(user: Manage, payload: PositionRequest, request: Request) -> dict[str, object]:
    repo = _repo(request)
    workspace_id = getattr(request.state, "workspace_id", "default")
    pos = CashPosition(
        workspace_id=workspace_id,
        organization_id=getattr(user, "organization_id", "org_default"),
        legal_entity_id=getattr(user, "legal_entity_id", "le_default"),
        bank_account_id=payload.bank_account_id,
        bank_name=payload.bank_name,
        currency=payload.currency,
        as_of_date=payload.as_of_date,
        cleared_balance_minor=int(payload.cleared_balance_minor),
        minimum_covenant_minor=int(payload.minimum_covenant_minor),
    )
    repo.save_position(pos)
    return {"status": "success", "bank_account_id": pos.bank_account_id, "currency": pos.currency}


@router.get("/positions/{bank_account_id}")
def get_position(user: Read, bank_account_id: str, request: Request) -> dict[str, object]:
    repo = _repo(request)
    workspace_id = getattr(request.state, "workspace_id", "default")
    pos = repo.get_position(
        workspace_id, getattr(user, "legal_entity_id", "le_default"), bank_account_id
    )
    if not pos:
        raise APIError(status_code=404, code="treasury_not_found", message="Position not found")
    return {
        "bank_account_id": pos.bank_account_id,
        "bank_name": pos.bank_name,
        "currency": pos.currency,
        "as_of_date": pos.as_of_date,
        "cleared_balance_minor": str(pos.cleared_balance_minor),
        "minimum_covenant_minor": str(pos.minimum_covenant_minor),
    }


@router.post("/flows")
def create_flow(user: Manage, payload: FlowRequest, request: Request) -> dict[str, object]:
    repo = _repo(request)
    workspace_id = getattr(request.state, "workspace_id", "default")
    flow = LiquidityFlow(
        flow_id=payload.flow_id,
        workspace_id=workspace_id,
        organization_id=getattr(user, "organization_id", "org_default"),
        legal_entity_id=getattr(user, "legal_entity_id", "le_default"),
        direction=payload.direction,
        source_type=payload.source_type,
        source_reference=payload.source_reference,
        currency=payload.currency,
        due_date=payload.due_date,
        amount_minor=int(payload.amount_minor),
        confidence_bps=payload.confidence_bps,
        status=payload.status,
    )
    repo.save_flow(flow)
    return {"status": "success", "flow_id": flow.flow_id}


@router.post("/forecast")
def generate_forecast(user: Read, payload: ForecastRequest, request: Request) -> dict[str, object]:
    repo = _repo(request)
    workspace_id = getattr(request.state, "workspace_id", "default")
    try:
        engine = repo.build_engine(
            workspace_id, getattr(user, "legal_entity_id", "le_default"), payload.bank_account_id
        )
    except ValueError as exc:
        raise APIError(status_code=404, code="treasury_position_missing", message=str(exc)) from exc

    scenario = None
    if payload.scenario:
        scenario = StressScenario(
            scenario_name=payload.scenario.scenario_name,
            ar_delay_days=payload.scenario.ar_delay_days,
            ar_haircut_bps=payload.scenario.ar_haircut_bps,
            ap_acceleration_days=payload.scenario.ap_acceleration_days,
            unplanned_outflow_minor=int(payload.scenario.unplanned_outflow_minor),
        )

    results = engine.forecast(
        horizon_days=payload.horizon_days,
        bucket_days=payload.bucket_days,
        scenario=scenario,
    )

    return {
        "status": "success",
        "currency": engine.position.currency,
        "buckets": [
            {
                "bucket_index": b.bucket_index,
                "start_date": b.start_date,
                "end_date": b.end_date,
                "opening_balance_minor": str(b.opening_balance_minor),
                "weighted_inflow_minor": str(b.weighted_inflow_minor),
                "weighted_outflow_minor": str(b.weighted_outflow_minor),
                "net_change_minor": str(b.net_change_minor),
                "closing_balance_minor": str(b.closing_balance_minor),
                "covenant_breached": b.covenant_breached,
            }
            for b in results
        ],
    }
