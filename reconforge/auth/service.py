"""Local user, RBAC, and SoD services."""

from __future__ import annotations

import sqlite3

from reconforge.audit import append_audit_event
from reconforge.auth.models import LocalUser
from reconforge.auth.passwords import hash_password, verify_password
from reconforge.auth.rbac import SoDCheckResult, check_object_action_permission, check_sod_conflict, has_permission
from reconforge.auth.repositories import AuthRepositoryError, RoleRepository, UserRepository


class AuthServiceError(ValueError):
    """Raised for safe, user-facing local auth service errors."""


class LocalAuthService:
    """Service layer for local users and RBAC."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self.users = UserRepository(connection)
        self.roles = RoleRepository(connection)

    def create_user(
        self,
        *,
        username: str,
        password: str,
        role: str,
        actor_label: str = "local-cli",
        display_name: str | None = None,
        email: str | None = None,
    ) -> LocalUser:
        try:
            if self.roles.get_role(role) is None:
                raise AuthRepositoryError("Role not found.")
            password_hash = hash_password(password)
            user = self.users.create(
                username=username, password_hash=password_hash, display_name=display_name, email=email
            )
            self.roles.assign_role(username=username, role_name=role)
            self._audit(
                actor_label=actor_label,
                object_type="user",
                object_id=user.id,
                action="user_created",
                metadata={"username": user.username, "role": role},
            )
            self._audit(
                actor_label=actor_label,
                object_type="user_role",
                object_id=user.id,
                action="role_assigned",
                metadata={"username": user.username, "role": role},
            )
        except (AuthRepositoryError, ValueError) as exc:
            raise AuthServiceError(str(exc)) from exc
        return user

    def init_admin(self, *, username: str, password: str, actor_label: str = "local-cli") -> LocalUser:
        return self.create_user(
            username=username, password=password, role="admin", actor_label=actor_label, display_name=username
        )

    def disable_user(self, *, username: str, actor_label: str = "local-cli") -> LocalUser:
        try:
            user = self.users.disable(username)
            self._audit(
                actor_label=actor_label,
                object_type="user",
                object_id=user.id,
                action="user_disabled",
                metadata={"username": user.username},
            )
        except AuthRepositoryError as exc:
            raise AuthServiceError(str(exc)) from exc
        return user

    def update_user(
        self,
        *,
        username: str,
        actor_label: str = "local-cli",
        display_name: str | None = None,
        email: str | None = None,
        disabled: bool | None = None,
    ) -> LocalUser:
        try:
            user = self.users.update_profile(username, display_name=display_name, email=email, disabled=disabled)
            self._audit(
                actor_label=actor_label,
                object_type="user",
                object_id=user.id,
                action="user_updated",
                metadata={
                    "username": user.username,
                    "display_name_changed": display_name is not None,
                    "email_changed": email is not None,
                    "disabled_changed": disabled is not None,
                },
            )
        except AuthRepositoryError as exc:
            raise AuthServiceError(str(exc)) from exc
        return user

    def change_password(self, *, username: str, password: str, actor_label: str = "local-cli") -> LocalUser:
        try:
            user = self.users.change_password(username, hash_password(password))
            self._audit(
                actor_label=actor_label,
                object_type="user",
                object_id=user.id,
                action="password_changed",
                metadata={"username": user.username},
            )
        except (AuthRepositoryError, ValueError) as exc:
            raise AuthServiceError(str(exc)) from exc
        return user

    def assign_role(self, *, username: str, role: str, actor_label: str = "local-cli") -> None:
        try:
            user = self._require_user(username)
            self.roles.assign_role(username=username, role_name=role)
            self._audit(
                actor_label=actor_label,
                object_type="user_role",
                object_id=user.id,
                action="role_assigned",
                metadata={"username": username, "role": role},
            )
        except AuthRepositoryError as exc:
            raise AuthServiceError(str(exc)) from exc

    def set_single_role(self, *, username: str, role: str, actor_label: str = "local-cli") -> None:
        try:
            user = self._require_user(username)
            before_roles = self.roles.user_roles(username)
            self.roles.set_single_role(username=username, role_name=role)
            after_roles = self.roles.user_roles(username)
            self._audit(
                actor_label=actor_label,
                object_type="user_role",
                object_id=user.id,
                action="role_changed",
                metadata={"username": username, "before_roles": before_roles, "after_roles": after_roles},
            )
        except AuthRepositoryError as exc:
            raise AuthServiceError(str(exc)) from exc

    def remove_role(self, *, username: str, role: str, actor_label: str = "local-cli") -> None:
        try:
            user = self._require_user(username)
            self.roles.remove_role(username=username, role_name=role)
            self._audit(
                actor_label=actor_label,
                object_type="user_role",
                object_id=user.id,
                action="role_removed",
                metadata={"username": username, "role": role},
            )
        except AuthRepositoryError as exc:
            raise AuthServiceError(str(exc)) from exc

    def authenticate_user(self, *, username: str, password: str) -> LocalUser | None:
        try:
            user = self.users.get_by_username(username)
            stored = self.users.get_password_hash(username)
        except AuthRepositoryError as exc:
            raise AuthServiceError(str(exc)) from exc
        if user is None or user.disabled or stored is None:
            return None
        return user if verify_password(password, stored) else None

    def user_has_permission(self, *, username: str, permission: str) -> bool:
        try:
            user = self._require_user(username)
            if user.disabled:
                return False
            return has_permission(self.roles.user_permissions(username), permission)
        except AuthRepositoryError as exc:
            raise AuthServiceError(str(exc)) from exc

    def user_can_perform_object_action(self, *, username: str, object_type: str, action: str) -> bool:
        try:
            user = self._require_user(username)
            if user.disabled:
                return False
            return check_object_action_permission(self.roles.user_permissions(username), object_type, action)
        except AuthRepositoryError as exc:
            raise AuthServiceError(str(exc)) from exc

    def check_sod(
        self,
        *,
        user_id: str,
        object_type: str,
        object_id: str,
        action: str,
        prior_actions: list[tuple[str, str, str, str]],
    ) -> SoDCheckResult:
        return check_sod_conflict(
            user_id=user_id,
            object_type=object_type,
            object_id=object_id,
            action=action,
            prior_actions=prior_actions,
        )

    def _require_user(self, username: str) -> LocalUser:
        user = self.users.get_by_username(username)
        if user is None:
            raise AuthRepositoryError("User not found.")
        return user

    def _audit(
        self, *, actor_label: str, object_type: str, object_id: str, action: str, metadata: dict[str, object]
    ) -> None:
        append_audit_event(
            self.connection,
            actor_label=actor_label,
            object_type=object_type,
            object_id=object_id,
            action=action,
            metadata=metadata,
        )
