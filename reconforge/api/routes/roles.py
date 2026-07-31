"""Role inspection routes for the local API."""

from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, Request

from reconforge.api.dependencies import get_local_db, require_any_permission
from reconforge.api.errors import APIError
from reconforge.api.server_identity import server_identity_enabled
from reconforge.auth import AuthRepositoryError, AuthServiceError, LocalAuthService
from reconforge.auth.models import LocalUser
from reconforge.db import DatabaseError

router = APIRouter(prefix="/roles", tags=["roles"])

ReadRoles = Annotated[LocalUser, Depends(require_any_permission({"db.read", "roles.manage", "users.manage"}))]


def _local_role_connection(request: Request, connection: sqlite3.Connection | None) -> sqlite3.Connection:
    if server_identity_enabled(request):
        raise APIError(
            status_code=409,
            code="local_identity_surface_disabled",
            message="Use the authoritative PostgreSQL access administration surface in server mode.",
        )
    if connection is None:
        raise APIError(status_code=503, code="database_unavailable", message="Local role storage is unavailable.")
    return connection


@router.get("")
def list_roles(
    current_user: ReadRoles,
    request: Request,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    """List local roles."""

    try:
        local_connection = _local_role_connection(request, connection)
        roles = [role.model_dump(mode="json") for role in LocalAuthService(local_connection).roles.list_roles()]
    except (DatabaseError, AuthRepositoryError, AuthServiceError) as exc:
        raise APIError(status_code=400, code="roles_read_failed", message="Unable to read local roles.") from exc
    return {"roles": roles}


@router.get("/{role_name}/permissions")
def role_permissions(
    role_name: str,
    current_user: ReadRoles,
    request: Request,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    """List permissions assigned to one local role."""

    try:
        local_connection = _local_role_connection(request, connection)
        permissions = LocalAuthService(local_connection).roles.role_permissions(role_name)
    except (DatabaseError, AuthRepositoryError, AuthServiceError) as exc:
        raise APIError(status_code=404, code="role_not_found", message=str(exc)) from exc
    return {"role": role_name, "permissions": permissions}
