from __future__ import annotations

from datetime import UTC, datetime

import pytest

from reconforge.application.access_administration import (
    AccessAdministrationApplicationService,
    AccessAdministrationError,
    AccessPermissionSummary,
    AccessRoleChange,
    AccessRolePage,
    AccessRoleSummary,
    UserRoleAssignmentChange,
)

NOW = datetime(2026, 7, 29, 21, 0, tzinfo=UTC)


def _role(*, version: int = 1) -> AccessRoleSummary:
    return AccessRoleSummary(
        id="role-reviewer",
        name="reviewer",
        description="Reviewer",
        active=True,
        lifecycle_version=version,
        permissions=("audit.read",),
        active_user_count=1,
        created_at="2026-07-29T20:00:00Z",
        updated_at="2026-07-29T20:00:00Z",
        retired_at=None,
        state_digest="a" * 64,
    )


class _Repository:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def list_permissions(self) -> tuple[AccessPermissionSummary, ...]:
        self.calls.append(("list_permissions", {}))
        return (AccessPermissionSummary("audit.read", "Read audit", 1, "b" * 64),)

    def list_roles(self, **kwargs: object) -> AccessRolePage:
        self.calls.append(("list_roles", kwargs))
        return AccessRolePage((_role(),))

    def create_role(self, **kwargs: object) -> AccessRoleChange:
        self.calls.append(("create_role", kwargs))
        return AccessRoleChange(_role(), True, 0, "audit-1")

    def update_role(self, **kwargs: object) -> AccessRoleChange:
        self.calls.append(("update_role", kwargs))
        return AccessRoleChange(_role(version=2), True, 1, "audit-2")

    def replace_role_permissions(self, **kwargs: object) -> AccessRoleChange:
        self.calls.append(("replace_role_permissions", kwargs))
        return AccessRoleChange(_role(version=2), True, 1, "audit-3")

    def replace_user_roles(self, **kwargs: object) -> UserRoleAssignmentChange:
        self.calls.append(("replace_user_roles", kwargs))
        return UserRoleAssignmentChange(
            "user-reviewer",
            "reviewer",
            2,
            ("role-reviewer",),
            ("reviewer",),
            True,
            1,
            "audit-4",
            "c" * 64,
        )


def test_access_service_normalizes_and_delegates_closed_role_lifecycle() -> None:
    repository = _Repository()
    service = AccessAdministrationApplicationService(repository, clock=lambda: NOW)

    assert service.list_permissions()[0].name == "audit.read"
    assert service.list_roles(limit=10).items[0].name == "reviewer"
    service.create_role(
        actor_user_id="USER-ADMIN",
        name="Review-Team",
        description="  Review   team  ",
        permissions=("reports.read", "audit.read"),
    )
    service.update_role(
        actor_user_id="user-admin",
        role_id="ROLE-REVIEWER",
        description="Updated",
        expected_lifecycle_version=1,
    )
    service.replace_role_permissions(
        actor_user_id="user-admin",
        role_id="role-reviewer",
        permissions=("reports.read", "audit.read"),
        expected_lifecycle_version=1,
    )
    service.replace_user_roles(
        actor_user_id="user-admin",
        user_id="USER-REVIEWER",
        role_ids=("ROLE-REVIEWER",),
        expected_user_lifecycle_version=1,
    )

    create = repository.calls[2][1]
    assert create["actor_user_id"] == "user-admin"
    assert create["name"] == "review-team"
    assert create["description"] == "Review team"
    assert create["permissions"] == ("audit.read", "reports.read")
    assert create["as_of"] == NOW
    assert repository.calls[-1][1]["role_ids"] == ("role-reviewer",)


@pytest.mark.parametrize(
    ("operation", "kwargs", "code"),
    [
        ("list_roles", {"limit": 0}, "access_page_limit_invalid"),
        (
            "create_role",
            {"actor_user_id": "admin", "name": "not a role", "description": "", "permissions": ()},
            "access_role_name_invalid",
        ),
        (
            "create_role",
            {"actor_user_id": "admin", "name": "role", "description": "", "permissions": ("audit.read", "AUDIT.READ")},
            "access_permission_set_invalid",
        ),
        (
            "update_role",
            {"actor_user_id": "admin", "role_id": "role-a", "expected_lifecycle_version": 1},
            "access_role_change_empty",
        ),
        (
            "replace_user_roles",
            {
                "actor_user_id": "admin",
                "user_id": "user-a",
                "role_ids": ("role-a", "ROLE-A"),
                "expected_user_lifecycle_version": 1,
            },
            "access_role_set_invalid",
        ),
    ],
)
def test_access_service_rejects_ambiguous_or_unbounded_inputs(
    operation: str, kwargs: dict[str, object], code: str
) -> None:
    service = AccessAdministrationApplicationService(_Repository(), clock=lambda: NOW)

    with pytest.raises(AccessAdministrationError) as captured:
        getattr(service, operation)(**kwargs)

    assert captured.value.code == code


def test_access_service_rejects_naive_or_subsecond_clock() -> None:
    for instant in (datetime(2026, 7, 29, 21, 0), datetime(2026, 7, 29, 21, 0, 0, 1, tzinfo=UTC)):
        service = AccessAdministrationApplicationService(_Repository(), clock=lambda instant=instant: instant)
        with pytest.raises(AccessAdministrationError) as captured:
            service.create_role(actor_user_id="admin", name="reviewer", description="", permissions=())
        assert captured.value.code == "access_time_invalid"
