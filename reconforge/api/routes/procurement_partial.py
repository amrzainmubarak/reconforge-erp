"""Authenticated PostgreSQL partial receiving and payable write operations."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from reconforge.api.errors import APIError
from reconforge.api.routes.procurement_operations import CreateRequest, Manage, Read, execute, required
from reconforge.api.server_finance_core import FinanceCoreExecutionScope
from reconforge.api.server_identity import request_execution_scope
from reconforge.auth.models import LocalUser
from reconforge.domain.finance_posting import PostingActor
from reconforge.domain.procurement_operations import READ, ProcurementPreparation
from reconforge.domain.procurement_partial import PartialQuantityPreparation
from reconforge.infrastructure.postgres_procurement_operations import (
    PERMISSIONS,
    PostgresProcurementOperationsRepository,
)
from reconforge.infrastructure.postgres_procurement_partial import OPERATIONS, PostgresProcurementPartialRepository

router = APIRouter(prefix="/procurement-partial", tags=["procurement-partial"])


class PartialOrderRequest(CreateRequest):
    number: str = Field(min_length=1, max_length=40)


class PartialQuantityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    command_id: str = Field(min_length=1, max_length=160)
    expected_version: int = Field(ge=1)
    quantity: str = Field(min_length=1, max_length=64)
    posting_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    period_id: str = Field(min_length=1, max_length=160)
    reason: str = Field(min_length=1, max_length=500)


class PartialActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    command_id: str = Field(min_length=1, max_length=160)
    expected_version: int = Field(ge=1)
    document_id: str | None = Field(default=None, min_length=1, max_length=160)
    reason: str = Field(min_length=1, max_length=500)


def _execute(request: Request, user: LocalUser, permissions: frozenset[str],
             operation: Callable[[PostgresProcurementPartialRepository, PostingActor, FinanceCoreExecutionScope], Any],
             *, organization_code: str = "", entity_code: str = "") -> Any:
    def invoke(shared: PostgresProcurementOperationsRepository, actor: PostingActor, bound: FinanceCoreExecutionScope) -> Any:
        return operation(PostgresProcurementPartialRepository(shared.connection, bound.tenant_id), actor, bound)
    return execute(request, user, permissions, invoke, organization_code=organization_code, entity_code=entity_code)


@router.post("/orders")
def create(request: Request, payload: PartialOrderRequest, user: Manage) -> dict[str, Any]:
    scope = request_execution_scope(request)
    if payload.workspace not in {"default", scope.workspace_id}:
        raise APIError(status_code=403, code="workspace_scope_denied", message="Workspace is outside current authority.")
    def run(repository: PostgresProcurementPartialRepository, actor: PostingActor, bound: FinanceCoreExecutionScope) -> dict[str, Any]:
        fields = payload.model_dump(exclude={"command_id"})
        fields["unit_price_minor"] = int(payload.unit_price_minor)
        prepared = replace(ProcurementPreparation(**fields), workspace=bound.workspace_id,
                           organization_code=bound.organization_code, entity_code=bound.entity_code)
        return repository.create(prepared, command_id=payload.command_id, actor=actor)
    return _execute(request, user, READ | PERMISSIONS["create"], run, organization_code=payload.organization_code, entity_code=payload.entity_code)


@router.get("/orders")
def list_orders(request: Request, user: Read) -> dict[str, Any]:
    return _execute(request, user, READ, lambda repository, actor, scope: {"records": repository.list_orders(scope.workspace_id, actor=actor)})


@router.get("/orders/{order_id}")
def get_order(request: Request, order_id: str, user: Read) -> dict[str, Any]:
    return _execute(request, user, READ, lambda repository, actor, scope: repository.get(order_id, actor=actor))


@router.get("/options")
def options(request: Request, user: Read) -> dict[str, Any]:
    return _execute(request, user, READ, lambda repository, actor, scope: repository.options(scope.workspace_id, scope.organization_code, scope.entity_code, actor=actor))


@router.get("/scopes")
def scopes(request: Request, user: Read) -> dict[str, Any]:
    return _execute(request, user, READ, lambda repository, actor, scope: {"records": repository.scopes(scope.workspace_id, actor=actor)})


def quantity_endpoint(operation: str) -> Callable[..., dict[str, Any]]:
    permissions = READ | PERMISSIONS[operation]
    def endpoint(request: Request, order_id: str, payload: PartialQuantityRequest,
                 user: LocalUser = Depends(required(permissions))) -> dict[str, Any]:
        prepared = PartialQuantityPreparation(**payload.model_dump(exclude={"command_id", "expected_version"}))
        return _execute(request, user, permissions, lambda repository, actor, scope:
            (repository.prepare_receipt if operation == "prepare-receipt" else repository.match_invoice)(order_id, prepared,
                expected_version=payload.expected_version, command_id=payload.command_id, actor=actor))
    endpoint.__name__ = "partial_" + operation.replace("-", "_")
    return endpoint


for operation in ("prepare-receipt", "match-invoice"):
    router.add_api_route("/orders/{order_id}/commands/" + operation, quantity_endpoint(operation), methods=["POST"])


def action_endpoint(operation: str) -> Callable[..., dict[str, Any]]:
    permissions = READ | PERMISSIONS[operation]
    def endpoint(request: Request, order_id: str, payload: PartialActionRequest,
                 user: LocalUser = Depends(required(permissions))) -> dict[str, Any]:
        return _execute(request, user, permissions, lambda repository, actor, scope:
            repository.act(order_id, operation, **payload.model_dump(), actor=actor))
    endpoint.__name__ = "partial_" + operation.replace("-", "_")
    return endpoint


for operation in OPERATIONS:
    router.add_api_route("/orders/{order_id}/commands/" + operation, action_endpoint(operation), methods=["POST"])
