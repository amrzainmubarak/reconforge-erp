"""Role inspection routes for the local API."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from typing import Annotated

from fastapi import APIRouter, Depends, Request

from reconforge.api.dependencies import get_local_db, require_any_permission
from reconforge.api.errors import APIError
from reconforge.api.server_identity import server_identity_enabled
from reconforge.auth import AuthRepositoryError, AuthServiceError, LocalAuthService
from reconforge.auth.field_access import project_local_role, project_local_role_permissions
from reconforge.auth.models import LocalUser
from reconforge.db import DatabaseError

router = APIRouter(prefix="/roles", tags=["roles"])

ReadRoles = Annotated[LocalUser, Depends(require_any_permission({"db.read", "roles.manage", "users.manage"}))]


def _project_local_roles(roles: object) -> list[dict[str, object]]:
    """Project local role records before they cross the API boundary."""

    if not isinstance(roles, (list, tuple)):
        raise APIError(
            status_code=503,
            code="roles_projection_failed",
            message="Role repository returned an invalid role collection.",
        )
    projected: list[dict[str, object]] = []
    try:
        for role in roles:
            if hasattr(role, "model_dump"):
                record = role.model_dump(mode="json")
            elif isinstance(role, Mapping):
                record = dict(role)
            else:
                raise TypeError("local role must be a model or mapping")
            projected.append(project_local_role(record).visible)
    except (TypeError, ValueError) as exc:
        raise APIError(
            status_code=503,
            code="roles_projection_failed",
            message="Role repository returned an invalid role contract.",
        ) from exc
    return projected


def _project_local_role_permissions(role_name: str, permissions: object) -> dict[str, object]:
    """Project local role permissions through the shared closed contract."""

    try:
        return project_local_role_permissions({"role": role_name, "permissions": permissions}).visible
    except (TypeError, ValueError) as exc:
        raise APIError(
            status_code=503,
            code="roles_projection_failed",
            message="Role repository returned an invalid permission contract.",
        ) from exc


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
        roles = _project_local_roles(LocalAuthService(local_connection).roles.list_roles())
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
    return _project_local_role_permissions(role_name, permissions)
