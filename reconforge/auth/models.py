"""Local auth and RBAC models."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from reconforge.domain.models import new_domain_id, utc_now_text


class _AuthModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LocalUser(_AuthModel):
    """A local user reference without password hash material."""

    id: str = Field(default_factory=lambda: new_domain_id("USR"))
    username: str
    display_name: str
    email: str | None = None
    disabled: bool = False
    created_at: str = Field(default_factory=utc_now_text)
    password_changed_at: str | None = None
    failed_login_count: int = Field(default=0, ge=0)
    locked_until: str | None = None


class LocalRole(_AuthModel):
    """A local RBAC role."""

    id: str
    name: str


class LocalPermission(_AuthModel):
    """A local RBAC permission."""

    name: str
    description: str


class RolePermission(_AuthModel):
    """Permission assigned to a role."""

    role_name: str
    permission_name: str


class SoDAction(_AuthModel):
    """A recorded action used for separation-of-duties checks."""

    user_id: str
    object_type: str
    object_id: str
    action: str
