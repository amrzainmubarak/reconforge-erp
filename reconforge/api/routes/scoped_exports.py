"""Authenticated, hierarchy-bound control-plane export routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict

from reconforge.api.dependencies import enforce_server_scoped_permission, require_permission
from reconforge.api.errors import APIError
from reconforge.api.server_identity import request_execution_scope
from reconforge.api.server_scoped_exports import (
    execute_postgres_scoped_export,
    server_scoped_exports_enabled,
)
from reconforge.application.scoped_exports import ScopedExportScope
from reconforge.auth.models import LocalUser
from reconforge.infrastructure.postgres_scoped_exports import PostgresScopedExportRepository

router = APIRouter(prefix="/exports", tags=["exports"])
ScopedExportRead = Annotated[LocalUser, Depends(require_permission("reports.read"))]


class ScopedExportResponse(BaseModel):
    """Closed response envelope for one deterministic control-plane export."""

    model_config = ConfigDict(extra="forbid")

    export: dict[str, object]
    digest: str
    byte_size: int
    source: dict[str, object]


@router.get("/scoped", response_model=ScopedExportResponse)
def read_scoped_export(request: Request, current_user: ScopedExportRead) -> dict[str, object]:
    """Return one bounded RLS-backed export for the authenticated hierarchy."""

    del current_user
    if not server_scoped_exports_enabled(request):
        raise APIError(
            status_code=501,
            code="scoped_export_server_only",
            message="Scoped control-plane exports require the explicit PostgreSQL server profile.",
        )
    scope = request_execution_scope(request)
    enforce_server_scoped_permission(
        request,
        permission="reports.read",
        tenant_id=scope.tenant_id,
        workspace_id=scope.workspace_id,
        entity_id=scope.legal_entity_id,
    )

    def snapshot(
        repository: PostgresScopedExportRepository, export_scope: ScopedExportScope
    ) -> dict[str, object]:
        value = repository.snapshot(export_scope)
        content = value.to_bytes()
        payload = {**value.payload_without_digest(), "artifact_digest": value.digest}
        return {
            "export": payload,
            "digest": value.digest,
            "byte_size": len(content),
            "source": {"kind": "postgresql-scoped-control-plane-export", "server_mode": True},
        }

    return execute_postgres_scoped_export(request, snapshot)


__all__ = ["router"]
