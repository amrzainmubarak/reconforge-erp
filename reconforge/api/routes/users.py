"""User management routes for the local API."""

from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from reconforge.api.dependencies import get_db, require_any_permission, require_permission
from reconforge.api.errors import APIError
from reconforge.auth import AuthRepositoryError, AuthServiceError, LocalAuthService
from reconforge.auth.models import LocalUser
from reconforge.db import DatabaseError

router = APIRouter(prefix="/users", tags=["users"])


class CreateUserRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str
    password: str
    role: str = "reviewer"
    display_name: str | None = None
    email: str | None = None


class PatchUserRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = None
    email: str | None = None
    disabled: bool | None = None


class RoleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str


ReadUsers = Annotated[LocalUser, Depends(require_any_permission({"db.read", "users.manage"}))]
ManageUsers = Annotated[LocalUser, Depends(require_permission("users.manage"))]


def user_payload(service: LocalAuthService, user: LocalUser) -> dict[str, object]:
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "email": user.email,
        "disabled": user.disabled,
        "created_at": user.created_at,
        "roles": service.roles.user_roles(user.username),
    }


@router.get("")
def list_users(
    current_user: ReadUsers,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    """List local users without credential material."""

    try:
        service = LocalAuthService(connection)
        users = [user_payload(service, user) for user in service.users.list()]
    except (DatabaseError, AuthRepositoryError, AuthServiceError) as exc:
        raise APIError(status_code=400, code="users_read_failed", message="Unable to read local users.") from exc
    return {"users": users}


@router.post("")
def create_user(
    payload: CreateUserRequest,
    current_user: ManageUsers,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    """Create a local user and assign one role."""

    try:
        service = LocalAuthService(connection)
        user = service.create_user(
            username=payload.username,
            password=payload.password,
            role=payload.role,
            actor_label=current_user.username,
            display_name=payload.display_name,
            email=payload.email,
        )
        return {"user": user_payload(service, user)}
    except (DatabaseError, AuthRepositoryError, AuthServiceError) as exc:
        raise APIError(status_code=400, code="user_create_failed", message=str(exc)) from exc


@router.patch("/{username}")
def patch_user(
    username: str,
    payload: PatchUserRequest,
    current_user: ManageUsers,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    """Update local user metadata."""

    try:
        service = LocalAuthService(connection)
        user = service.update_user(
            username=username,
            actor_label=current_user.username,
            display_name=payload.display_name,
            email=payload.email,
            disabled=payload.disabled,
        )
        return {"user": user_payload(service, user)}
    except (DatabaseError, AuthRepositoryError, AuthServiceError) as exc:
        raise APIError(status_code=400, code="user_update_failed", message=str(exc)) from exc


@router.post("/{username}/disable")
def disable_user(
    username: str,
    current_user: ManageUsers,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    """Disable a local user."""

    try:
        service = LocalAuthService(connection)
        user = service.disable_user(username=username, actor_label=current_user.username)
        return {"user": user_payload(service, user)}
    except (DatabaseError, AuthRepositoryError, AuthServiceError) as exc:
        raise APIError(status_code=400, code="user_disable_failed", message=str(exc)) from exc


@router.post("/{username}/roles")
def assign_role(
    username: str,
    payload: RoleRequest,
    current_user: ManageUsers,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    """Assign a role to a local user."""

    try:
        service = LocalAuthService(connection)
        service.assign_role(username=username, role=payload.role, actor_label=current_user.username)
        return {"username": username, "roles": service.roles.user_roles(username)}
    except (DatabaseError, AuthRepositoryError, AuthServiceError) as exc:
        raise APIError(status_code=400, code="role_assign_failed", message=str(exc)) from exc


@router.delete("/{username}/roles/{role_name}")
def remove_role(
    username: str,
    role_name: str,
    current_user: ManageUsers,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    """Remove a role from a local user."""

    try:
        service = LocalAuthService(connection)
        service.remove_role(username=username, role=role_name, actor_label=current_user.username)
        return {"username": username, "roles": service.roles.user_roles(username)}
    except (DatabaseError, AuthRepositoryError, AuthServiceError) as exc:
        raise APIError(status_code=400, code="role_remove_failed", message=str(exc)) from exc


@router.get("/{username}/permissions")
def user_permissions(
    username: str,
    current_user: ReadUsers,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    """List effective permissions for a local user."""

    try:
        service = LocalAuthService(connection)
        permissions = sorted(service.roles.user_permissions(username))
    except (DatabaseError, AuthRepositoryError, AuthServiceError) as exc:
        raise APIError(status_code=400, code="permissions_read_failed", message=str(exc)) from exc
    return {"username": username, "permissions": permissions}
