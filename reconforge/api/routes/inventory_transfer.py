"""Typed same-entity transfer commands and complete immutable original receipts."""
from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from reconforge.api.errors import APIError
from reconforge.api.routes.finance_posting import _actor
from reconforge.api.routes.procurement_operations import required
from reconforge.api.server_finance_core import (
    FinanceCoreExecutionScope,
    execute_postgres_finance_core_scoped,
    server_finance_core_enabled,
)
from reconforge.application.inventory_transfer import InventoryTransferService
from reconforge.auth.models import LocalUser
from reconforge.domain.finance_posting import FinancePostingError, PostingActor, digest_payload
from reconforge.domain.inventory_transfer import PERMISSIONS, READ, TransferInversePreparation, TransferPreparation
from reconforge.infrastructure.postgres_inventory_transfer import PostgresInventoryTransferRepository
from reconforge.platform.common import PlatformError

router = APIRouter(prefix="/inventory-transfer", tags=["inventory-transfer"])
Read = Annotated[LocalUser, Depends(required(READ))]
Create = Annotated[LocalUser, Depends(required(PERMISSIONS["create"]))]
Review = Annotated[LocalUser, Depends(required(PERMISSIONS["review"]))]
Post = Annotated[LocalUser, Depends(required(PERMISSIONS["post"]))]
Cancel = Annotated[LocalUser, Depends(required(PERMISSIONS["cancel"]))]
Inverse = Annotated[LocalUser, Depends(required(PERMISSIONS["inverse-create"]))]


class TransferRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    command_id: str = Field(min_length=1, max_length=140)
    number: str = Field(pattern=r"^[A-Z0-9][A-Z0-9._/-]{0,63}$")
    item_code: str = Field(min_length=1, max_length=64)
    quantity: str = Field(pattern=r"^[0-9]{1,19}(?:\.[0-9]{1,6})?$")
    from_location: str = Field(min_length=3, max_length=129)
    to_location: str = Field(min_length=3, max_length=129)
    period_id: str = Field(min_length=1, max_length=160)
    posting_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    reason: str = Field(min_length=1, max_length=500)


class TransferPhaseRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    command_id: str = Field(min_length=1, max_length=140)
    expected_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_version: int = Field(ge=1, le=3)
    reason: str = Field(min_length=1, max_length=500)


class TransferInverseRequest(TransferPhaseRequest):
    number: str = Field(pattern=r"^[A-Z0-9][A-Z0-9._/-]{0,63}$")
    period_id: str = Field(min_length=1, max_length=160)
    posting_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")


def project_transfer(value: Any, key: str = "") -> Any:
    if isinstance(value, dict):
        return {name: project_transfer(item, name) for name, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value] if key == "exposed_amounts_minor" else [project_transfer(item) for item in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    if type(value) is int and (key.endswith(("_minor", "_scaled")) or abs(value) > 9_007_199_254_740_991):
        return str(value)
    return value


def scope_fields(scope: FinanceCoreExecutionScope) -> dict[str, str]:
    if scope.organization_id is None or scope.legal_entity_id is None:
        raise APIError(status_code=403, code="inventory_transfer_scope_denied", message="Select an authorized organization and legal entity.")
    return {"workspace_id": scope.workspace_id, "organization_id": scope.organization_id, "legal_entity_id": scope.legal_entity_id}


def execute(request: Request, user: LocalUser,
            action: Callable[[InventoryTransferService, PostingActor, FinanceCoreExecutionScope], Any],
            *, payload: BaseModel | None = None) -> Any:
    if not server_finance_core_enabled(request):
        raise APIError(status_code=503, code="inventory_transfer_backend_unavailable", message="Native transfer custody requires PostgreSQL.")
    actor = _actor(request, user)

    def invoke(finance: Any, scope: FinanceCoreExecutionScope) -> Any:
        scope_fields(scope)
        try:
            repository = PostgresInventoryTransferRepository(finance.connection, scope.tenant_id)
            result = action(InventoryTransferService(repository), actor, scope)
            projected = project_transfer(result)
            if payload is not None:
                submitted = payload.model_dump(mode="json", exclude_unset=True)
                receipt = repository.command_receipt(result["source"]["id"], str(submitted["command_id"]), result, actor=actor)
                projected["command_ack"] = {**project_transfer(receipt), "response_digest": digest_payload(projected)}
                projected["submitted_request"] = submitted
                projected["submitted_request_digest"] = digest_payload(submitted)
            return projected
        except FinancePostingError as exc:
            raise APIError(status_code=403 if "denied" in exc.code else 404 if "not_found" in exc.code else 409,
                code=exc.code, message=str(exc)) from exc
        except PlatformError as exc:
            raise APIError(status_code=409, code="inventory_transfer_native_conflict", message=str(exc)) from exc

    return execute_postgres_finance_core_scoped(request, invoke)


@router.get("/transfers")
def list_transfers(request: Request, user: Read) -> dict[str, Any]:
    return execute(request, user, lambda service, actor, scope: service.list_transfers(scope_fields(scope), actor=actor))


@router.get("/transfers/{identifier}")
def get_transfer(request: Request, identifier: str, user: Read) -> dict[str, Any]:
    return execute(request, user, lambda service, actor, scope: {"source": service.get(identifier, actor=actor)})


@router.get("/transfers/{identifier}/evidence")
def get_evidence(request: Request, identifier: str, user: Read) -> dict[str, Any]:
    return execute(request, user, lambda service, actor, scope: service.evidence(identifier, actor=actor))


@router.post("/transfers")
def create_transfer(request: Request, payload: TransferRequest, user: Create) -> dict[str, Any]:
    def invoke(service: InventoryTransferService, actor: PostingActor, scope: FinanceCoreExecutionScope) -> dict[str, Any]:
        prepared = TransferPreparation(**payload.model_dump(exclude={"command_id"}), scope=scope_fields(scope))
        return service.create(prepared, command_id=payload.command_id, actor=actor)
    return execute(request, user, invoke, payload=payload)


@router.post("/transfers/{identifier}/review")
def review_transfer(request: Request, identifier: str, payload: TransferPhaseRequest, user: Review) -> dict[str, Any]:
    return execute(request, user, lambda service, actor, scope: service.act(identifier, "review", **payload.model_dump(), actor=actor), payload=payload)


@router.post("/transfers/{identifier}/post")
def post_transfer(request: Request, identifier: str, payload: TransferPhaseRequest, user: Post) -> dict[str, Any]:
    return execute(request, user, lambda service, actor, scope: service.act(identifier, "post", **payload.model_dump(), actor=actor), payload=payload)


@router.post("/transfers/{identifier}/cancel")
def cancel_transfer(request: Request, identifier: str, payload: TransferPhaseRequest, user: Cancel) -> dict[str, Any]:
    return execute(request, user, lambda service, actor, scope: service.act(identifier, "cancel", **payload.model_dump(), actor=actor), payload=payload)


@router.post("/transfers/{identifier}/inverse")
def create_inverse(request: Request, identifier: str, payload: TransferInverseRequest, user: Inverse) -> dict[str, Any]:
    return execute(request, user, lambda service, actor, scope: service.create_inverse(
        TransferInversePreparation(original_id=identifier, **payload.model_dump(exclude={"command_id"})), command_id=payload.command_id, actor=actor), payload=payload)
