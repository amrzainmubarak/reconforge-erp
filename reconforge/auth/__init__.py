"""Local users, password hashing, RBAC, and SoD primitives."""

from __future__ import annotations

from reconforge.auth.models import LocalPermission, LocalRole, LocalUser, RolePermission, SoDAction
from reconforge.auth.passwords import PasswordHash, hash_password, verify_password
from reconforge.auth.rbac import (
    SoDCheckResult,
    check_object_action_permission,
    check_sod_conflict,
    has_permission,
    required_permission_for_action,
)
from reconforge.auth.repositories import AuthRepositoryError, RoleRepository, UserRepository
from reconforge.auth.service import AuthServiceError, LocalAuthService

__all__ = [
    "AuthRepositoryError",
    "AuthServiceError",
    "LocalAuthService",
    "LocalPermission",
    "LocalRole",
    "LocalUser",
    "PasswordHash",
    "RolePermission",
    "RoleRepository",
    "SoDAction",
    "SoDCheckResult",
    "UserRepository",
    "check_object_action_permission",
    "check_sod_conflict",
    "has_permission",
    "hash_password",
    "required_permission_for_action",
    "verify_password",
]
