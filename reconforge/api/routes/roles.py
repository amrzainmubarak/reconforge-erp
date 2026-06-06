"""Role inspection routes for the local API."""

from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends

from reconforge.api.dependencies import get_db, require_any_permission
from reconforge.api.errors import APIError
from reconforge.auth import AuthRepositoryError, AuthServiceError, LocalAuthService
from reconforge.auth.models import LocalUser
from reconforge.db import DatabaseError

router = APIRouter(prefix="/roles", tags=["roles"])

ReadRoles = Annotated[LocalUser, Depends(require_any_permission({"db.read", "roles.manage", "users.manage"}))]


@router.get("")
def list_roles(
    current_user: ReadRoles,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    """List local roles."""

    try:
        roles = [role.model_dump(mode="json") for role in LocalAuthService(connection).roles.list_roles()]
    except (DatabaseError, AuthRepositoryError, AuthServiceError) as exc:
        raise APIError(status_code=400, code="roles_read_failed", message="Unable to read local roles.") from exc
    return {"roles": roles}


@router.get("/{role_name}/permissions")
def role_permissions(
    role_name: str,
    current_user: ReadRoles,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    """List permissions assigned to one local role."""

    try:
        permissions = LocalAuthService(connection).roles.role_permissions(role_name)
    except (DatabaseError, AuthRepositoryError, AuthServiceError) as exc:
        raise APIError(status_code=404, code="role_not_found", message=str(exc)) from exc
    return {"role": role_name, "permissions": permissions}
