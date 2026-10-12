"""Authenticated native paid landed-cost receiving commands."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from reconforge.api.routes.procurement_operations import Read, execute, required
from reconforge.auth.models import LocalUser
from reconforge.domain.landed_cost import LandedCostPreparation
from reconforge.domain.procurement_operations import READ
from reconforge.domain.procurement_partial import ProcurementLineQuantity
from reconforge.infrastructure.postgres_landed_cost import PostgresLandedCostRepository
from reconforge.infrastructure.postgres_procurement_operations import PERMISSIONS

router = APIRouter(prefix="/landed-cost", tags=["landed-cost"])
PREPARE = READ | PERMISSIONS["prepare-receipt"] | PERMISSIONS["prepare-payment"]
REVIEW = READ | PERMISSIONS["review-receipt"] | PERMISSIONS["review-payment"]
POST = READ | PERMISSIONS["receive"] | PERMISSIONS["pay"]


class AllocationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    line_id: str = Field(min_length=1, max_length=160)
    quantity: str = Field(min_length=1, max_length=64)


class PreparationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    command_id: str = Field(min_length=1, max_length=140)
    number: str = Field(min_length=1, max_length=40)
    order_id: str = Field(min_length=1, max_length=160)
    expected_version: int = Field(ge=1)
    lines: list[AllocationRequest] = Field(min_length=1, max_length=128)
    freight_minor: str = Field(pattern=r"^(0|[1-9][0-9]{0,18})$")
    duty_minor: str = Field(pattern=r"^(0|[1-9][0-9]{0,18})$")
    posting_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    period_id: str = Field(min_length=1, max_length=160)
    reason: str = Field(min_length=1, max_length=500)


class ActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    command_id: str = Field(min_length=1, max_length=140)
    expected_plan_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    reason: str = Field(min_length=1, max_length=500)


@router.post("/plans")
def prepare(request: Request, payload: PreparationRequest,
            user: LocalUser = Depends(required(PREPARE))) -> dict[str, Any]:
    prepared = LandedCostPreparation(**payload.model_dump(exclude={"command_id", "lines", "freight_minor", "duty_minor"}),
        freight_minor=int(payload.freight_minor), duty_minor=int(payload.duty_minor),
        lines=tuple(ProcurementLineQuantity(**line.model_dump()) for line in payload.lines))
    return execute(request, user, PREPARE, lambda shared, actor, scope:
        PostgresLandedCostRepository(shared.connection, scope.tenant_id).prepare(prepared, command_id=payload.command_id, actor=actor))


@router.get("/orders/{order_id}")
def list_plans(request: Request, order_id: str, user: Read, after: str = Query(default="", max_length=160)) -> dict[str, Any]:
    return execute(request, user, READ, lambda shared, actor, scope:
        PostgresLandedCostRepository(shared.connection, scope.tenant_id).list_for_order(order_id, actor=actor, after=after))


@router.get("/plans/{identifier}")
def get_plan(request: Request, identifier: str, user: Read) -> dict[str, Any]:
    return execute(request, user, READ, lambda shared, actor, scope:
        PostgresLandedCostRepository(shared.connection, scope.tenant_id).get(identifier, actor=actor))


@router.post("/plans/{identifier}/review")
def review(request: Request, identifier: str, payload: ActionRequest,
           user: LocalUser = Depends(required(REVIEW))) -> dict[str, Any]:
    return execute(request, user, REVIEW, lambda shared, actor, scope:
        PostgresLandedCostRepository(shared.connection, scope.tenant_id).act(identifier, "review", **payload.model_dump(), actor=actor))


@router.post("/plans/{identifier}/post")
def post(request: Request, identifier: str, payload: ActionRequest,
         user: LocalUser = Depends(required(POST))) -> dict[str, Any]:
    return execute(request, user, POST, lambda shared, actor, scope:
        PostgresLandedCostRepository(shared.connection, scope.tenant_id).act(identifier, "post", **payload.model_dump(), actor=actor))


@router.post("/plans/{identifier}/cancel")
def cancel(request: Request, identifier: str, payload: ActionRequest,
           user: LocalUser = Depends(required(REVIEW))) -> dict[str, Any]:
    return execute(request, user, REVIEW, lambda shared, actor, scope:
        PostgresLandedCostRepository(shared.connection, scope.tenant_id).cancel(identifier, **payload.model_dump(), actor=actor))
