"""FastAPI routes for Multi-Level BOM Explosion, Engineering Revisions, and MRP Shortage Netting."""

from __future__ import annotations

import sqlite3
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from reconforge.api.dependencies import require_permission
from reconforge.api.errors import APIError
from reconforge.auth.models import LocalUser
from reconforge.domain.manufacturing_bom_explosion import (
    BillOfMaterials,
    BOMComponentLine,
)
from reconforge.infrastructure.sqlite_manufacturing_bom import (
    SqliteManufacturingBOMRepository,
)

router = APIRouter(prefix="/manufacturing/bom", tags=["manufacturing-bom"])
Read = Annotated[LocalUser, Depends(require_permission("manufacturing_execution.read"))]
Manage = Annotated[LocalUser, Depends(require_permission("manufacturing_execution.manage"))]


def _repo(request: Request) -> SqliteManufacturingBOMRepository:
    db_path = getattr(request.app.state, "db_path", None)
    if db_path is None:
        raise APIError(status_code=500, code="db_not_configured", message="API database path is not configured.")
    conn = sqlite3.connect(db_path)
    return SqliteManufacturingBOMRepository(conn)


class ComponentLinePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    line_number: int = Field(ge=1)
    component_item_id: str = Field(min_length=1, max_length=64)
    component_name: str = Field(min_length=1, max_length=128)
    component_type: Literal["raw_material", "subassembly", "finished_good"]
    quantity_per_parent: int = Field(ge=1)
    scrap_factor_bps: int = Field(default=0, ge=0, le=50000)
    substitute_item_id: str | None = None
    substitute_ratio_bps: int = Field(default=10000, ge=0, le=50000)


class BOMRegistrationPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    bom_id: str = Field(min_length=1, max_length=64)
    item_id: str = Field(min_length=1, max_length=64)
    revision: str = Field(min_length=1, max_length=32)
    status: Literal["draft", "approved", "obsolete"]
    effective_from: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    effective_to: str | None = Field(default=None, pattern=r"^(\d{4}-\d{2}-\d{2})?$")
    base_quantity: int = Field(default=1, ge=1)
    components: list[ComponentLinePayload] = Field(min_length=1)


class ExplosionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    item_id: str = Field(min_length=1, max_length=64)
    required_quantity: int = Field(ge=1)
    as_of_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    specific_revision: str | None = None


class NettingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    item_id: str = Field(min_length=1, max_length=64)
    required_quantity: int = Field(ge=1)
    as_of_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    inventory_on_hand: dict[str, int] = Field(default_factory=dict)
    scheduled_receipts: dict[str, int] = Field(default_factory=dict)
    lot_sizing: dict[str, tuple[int, int]] = Field(default_factory=dict)


@router.post("")
def register_bom(user: Manage, payload: BOMRegistrationPayload, request: Request) -> dict[str, object]:
    repo = _repo(request)
    components = tuple(
        BOMComponentLine(
            line_number=c.line_number,
            component_item_id=c.component_item_id,
            component_name=c.component_name,
            component_type=c.component_type,
            quantity_per_parent=c.quantity_per_parent,
            scrap_factor_bps=c.scrap_factor_bps,
            substitute_item_id=c.substitute_item_id,
            substitute_ratio_bps=c.substitute_ratio_bps,
        )
        for c in payload.components
    )
    bom = BillOfMaterials(
        bom_id=payload.bom_id,
        item_id=payload.item_id,
        revision=payload.revision,
        status=payload.status,
        effective_from=payload.effective_from,
        effective_to=payload.effective_to,
        base_quantity=payload.base_quantity,
        components=components,
    )
    repo.save_bom(bom)
    return {"status": "success", "bom_id": bom.bom_id, "item_id": bom.item_id, "revision": bom.revision}


@router.get("/{item_id}")
def get_bom(user: Read, item_id: str, request: Request, revision: str | None = None) -> dict[str, object]:
    repo = _repo(request)
    bom = repo.get_bom(item_id, revision)
    if not bom:
        raise APIError(status_code=404, code="bom_not_found", message=f"BOM not found for item {item_id}")
    return {
        "bom_id": bom.bom_id,
        "item_id": bom.item_id,
        "revision": bom.revision,
        "status": bom.status,
        "effective_from": bom.effective_from,
        "effective_to": bom.effective_to,
        "base_quantity": bom.base_quantity,
        "components": [
            {
                "line_number": c.line_number,
                "component_item_id": c.component_item_id,
                "component_name": c.component_name,
                "component_type": c.component_type,
                "quantity_per_parent": c.quantity_per_parent,
                "scrap_factor_bps": c.scrap_factor_bps,
                "substitute_item_id": c.substitute_item_id,
            }
            for c in bom.components
        ],
    }


@router.post("/explode")
def explode_bom(user: Read, payload: ExplosionRequest, request: Request) -> dict[str, object]:
    repo = _repo(request)
    engine = repo.build_engine()
    try:
        results = engine.explode(
            payload.item_id,
            payload.required_quantity,
            payload.as_of_date,
            specific_revision=payload.specific_revision,
        )
    except Exception as exc:
        raise APIError(status_code=400, code="bom_explosion_failed", message=str(exc)) from exc

    return {
        "status": "success",
        "item_id": payload.item_id,
        "required_quantity": payload.required_quantity,
        "exploded_lines": [
            {
                "depth": r.depth,
                "parent_item_id": r.parent_item_id,
                "item_id": r.item_id,
                "item_type": r.item_type,
                "path": r.path,
                "gross_quantity": r.gross_quantity,
                "scrap_quantity": r.scrap_quantity,
                "total_required_quantity": r.total_required_quantity,
            }
            for r in results
        ],
    }


@router.post("/net-requirements")
def calculate_net_requirements(user: Read, payload: NettingRequest, request: Request) -> dict[str, object]:
    repo = _repo(request)
    engine = repo.build_engine()
    try:
        exploded = engine.explode(payload.item_id, payload.required_quantity, payload.as_of_date)
        net_reqs = engine.calculate_net_requirements(
            exploded, payload.inventory_on_hand, payload.scheduled_receipts, payload.lot_sizing
        )
    except Exception as exc:
        raise APIError(status_code=400, code="mrp_netting_failed", message=str(exc)) from exc

    return {
        "status": "success",
        "item_id": payload.item_id,
        "net_requirements": [
            {
                "item_id": n.item_id,
                "item_type": n.item_type,
                "gross_required": n.gross_required,
                "on_hand": n.on_hand,
                "scheduled_receipts": n.scheduled_receipts,
                "net_shortage": n.net_shortage,
                "planned_order_quantity": n.planned_order_quantity,
            }
            for n in net_reqs
        ],
    }
