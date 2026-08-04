"""Authenticated API for effective-dated consolidation ownership masters."""

from __future__ import annotations

import sqlite3
from decimal import Decimal, InvalidOperation
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from reconforge.api.dependencies import get_local_db, require_any_permission, require_permission
from reconforge.api.errors import APIError
from reconforge.api.server_consolidation_ownership import (
    execute_postgres_consolidation_ownership,
    server_consolidation_ownership_enabled,
)
from reconforge.api.server_identity import RequestExecutionScope, request_execution_scope
from reconforge.application.consolidation_ownership import ConsolidationOwnershipApplicationService
from reconforge.auth.models import LocalUser
from reconforge.domain.consolidation import ConsolidationError
from reconforge.domain.consolidation_lifecycle import ConsolidationOwnershipInterest
from reconforge.infrastructure.sqlite_consolidation_ownership import SQLiteConsolidationOwnershipRepository
from reconforge.platform.common import PlatformError

router = APIRouter(prefix="/consolidation-ownership", tags=["consolidation-ownership"])
OwnershipRead = Annotated[LocalUser, Depends(require_any_permission({"finance_core.read", "finance_core.manage"}))]
OwnershipManage = Annotated[LocalUser, Depends(require_permission("finance_core.manage"))]


class OwnershipInterestRequest(BaseModel):
    """Strict wire representation for one immutable ownership revision."""

    model_config = ConfigDict(extra="forbid", strict=True)

    group_code: str = Field(min_length=1, max_length=160)
    workspace: str = Field(default="default", min_length=1, max_length=160)
    interest_id: str = Field(min_length=1, max_length=160)
    parent_entity_code: str = Field(min_length=1, max_length=160)
    subsidiary_entity_code: str = Field(min_length=1, max_length=160)
    direct_ownership_percentage: str = Field(
        pattern=r"^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$", min_length=1, max_length=128
    )
    effective_from: str = Field(min_length=10, max_length=10)
    effective_to: str = Field(default="", max_length=10)
    version: str = Field(pattern=r"^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)$")
    source_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    approved_by: str = Field(min_length=1, max_length=160)
    approved_at: str = Field(min_length=1, max_length=64)

    def to_domain(self, *, prepared_by: str) -> ConsolidationOwnershipInterest:
        try:
            return ConsolidationOwnershipInterest(
                interest_id=self.interest_id,
                parent_entity_code=self.parent_entity_code,
                subsidiary_entity_code=self.subsidiary_entity_code,
                direct_ownership_percentage=Decimal(self.direct_ownership_percentage),
                effective_from=self.effective_from,
                effective_to=self.effective_to,
                version=self.version,
                source_digest=self.source_digest,
                prepared_by=prepared_by,
                approved_by=self.approved_by,
                approved_at=self.approved_at,
            )
        except (ConsolidationError, InvalidOperation, TypeError, ValueError) as exc:
            raise APIError(
                status_code=400,
                code="consolidation_ownership_request_invalid",
                message="Ownership input failed deterministic validation.",
            ) from exc


def _repository(connection: sqlite3.Connection | None) -> SQLiteConsolidationOwnershipRepository:
    if connection is None:
        raise APIError(status_code=500, code="local_database_not_configured", message="Local database is not configured.")
    return SQLiteConsolidationOwnershipRepository(connection)


def _server_scope(request: Request, requested_workspace: str) -> RequestExecutionScope:
    scope = request_execution_scope(request)
    if requested_workspace.strip() not in {"", "default", scope.workspace_id}:
        raise APIError(status_code=403, code="workspace_scope_denied", message="Workspace scope is not authorized.")
    return scope


def _server_source() -> dict[str, object]:
    return {"kind": "postgresql-consolidation-ownership", "server_mode": True}


@router.post("/interests")
def save_interest(
    request: Request,
    payload: OwnershipInterestRequest,
    current_user: OwnershipManage,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    """Persist one immutable, maker-checker ownership revision."""

    if server_consolidation_ownership_enabled(request):
        scope = _server_scope(request, payload.workspace)
        interest = payload.to_domain(prepared_by=current_user.id)
        saved = execute_postgres_consolidation_ownership(
            request,
            lambda repository, _tenant: ConsolidationOwnershipApplicationService(repository).save(
                interest,
                group_code=payload.group_code,
                workspace=scope.workspace_id,
                actor_label=current_user.id,
            ),
        )
        return {"interest": saved, "source": _server_source()}

    interest = payload.to_domain(prepared_by=current_user.username)
    try:
        saved = ConsolidationOwnershipApplicationService(_repository(connection)).save(
            interest,
            group_code=payload.group_code,
            workspace=payload.workspace,
            actor_label=current_user.username,
        )
    except (PlatformError, sqlite3.DatabaseError) as exc:
        raise APIError(status_code=400, code="consolidation_ownership_request_invalid", message=str(exc)) from exc
    return {"interest": saved, "source": {"kind": "sqlite-consolidation-ownership", "workspace": payload.workspace}}


@router.get("/effective")
def resolve_effective(
    request: Request,
    current_user: OwnershipRead,
    group_code: str = Query(min_length=1, max_length=160),
    reporting_date: str = Query(min_length=10, max_length=10),
    workspace: str = Query(default="default", min_length=1, max_length=160),
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    """Resolve one deterministic effective ownership set by reporting date."""

    if server_consolidation_ownership_enabled(request):
        scope = _server_scope(request, workspace)
        interests = execute_postgres_consolidation_ownership(
            request,
            lambda repository, _tenant: ConsolidationOwnershipApplicationService(repository).resolve_effective(
                group_code=group_code,
                reporting_date=reporting_date,
                workspace=scope.workspace_id,
                actor_label=current_user.id,
            ),
        )
        return {"interests": [interest.to_input_dict() for interest in interests], "source": _server_source()}

    try:
        interests = ConsolidationOwnershipApplicationService(_repository(connection)).resolve_effective(
            group_code=group_code,
            reporting_date=reporting_date,
            workspace=workspace,
            actor_label=current_user.username,
        )
    except (PlatformError, sqlite3.DatabaseError) as exc:
        raise APIError(status_code=400, code="consolidation_ownership_resolution_failed", message=str(exc)) from exc
    return {
        "interests": [interest.to_input_dict() for interest in interests],
        "source": {"kind": "sqlite-consolidation-ownership", "workspace": workspace},
    }


__all__ = ["OwnershipInterestRequest", "resolve_effective", "router", "save_interest"]
