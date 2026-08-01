from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from reconforge.auth.scim import (
    SCIM_GROUP_SCHEMA,
    SCIM_USER_SCHEMA,
    SCIMError,
    SCIMGroup,
    SCIMGroupWrite,
    SCIMService,
    SCIMUser,
    SCIMUserWrite,
    scim_timestamp,
)


class MemoryRepository:
    def __init__(self) -> None:
        self.users: dict[tuple[str, str, str], SCIMUser] = {}
        self.groups: dict[tuple[str, str, str], SCIMGroup] = {}

    def put_user(self, *, tenant_id: str, domain: str, resource: SCIMUserWrite) -> tuple[SCIMUser, bool]:
        key = (tenant_id, domain, resource.externalId)
        previous = self.users.get(key)
        now = datetime(2026, 7, 28, tzinfo=UTC)
        user = SCIMUser(
            id=previous.id if previous else f"usr-{len(self.users) + 1}",
            provisioning_domain=domain,
            external_id=resource.externalId,
            username=resource.userName,
            display_name=resource.displayName or resource.userName,
            email=resource.emails[0].value if resource.emails else None,
            active=resource.active,
            version=(previous.version + 1) if previous else 1,
            created_at=previous.created_at if previous else now,
            updated_at=now,
        )
        self.users[key] = user
        return user, previous is None

    def set_user_active(self, *, tenant_id: str, domain: str, resource_id: str, active: bool) -> SCIMUser:
        found = next((value for key, value in self.users.items() if key[:2] == (tenant_id, domain) and value.id == resource_id), None)
        if found is None:
            raise SCIMError("Resource was not found.", scim_type="invalidValue")
        updated = SCIMUser(**{**found.__dict__, "active": active, "version": found.version + 1})
        self.users[(tenant_id, domain, found.external_id)] = updated
        return updated

    def put_group(self, *, tenant_id: str, domain: str, resource: SCIMGroupWrite) -> tuple[SCIMGroup, bool]:
        known = {user.id for key, user in self.users.items() if key[:2] == (tenant_id, domain)}
        members = tuple(member.value for member in resource.members)
        if not set(members).issubset(known):
            raise SCIMError("Group contains an unknown member.")
        key = (tenant_id, domain, resource.externalId)
        previous = self.groups.get(key)
        now = datetime(2026, 7, 28, tzinfo=UTC)
        group = SCIMGroup(
            id=previous.id if previous else f"grp-{len(self.groups) + 1}",
            provisioning_domain=domain,
            external_id=resource.externalId,
            display_name=resource.displayName,
            member_ids=members,
            version=(previous.version + 1) if previous else 1,
            created_at=previous.created_at if previous else now,
            updated_at=now,
        )
        self.groups[key] = group
        return group, previous is None


class Audit:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def record(self, **event: object) -> None:
        self.events.append(event)


def user_write(**overrides: object) -> SCIMUserWrite:
    values: dict[str, object] = {
        "schemas": (SCIM_USER_SCHEMA,),
        "externalId": "employee-42",
        "userName": "Analyst@example.com",
        "displayName": "  Example   Analyst  ",
        "emails": ({"value": "ANALYST@example.com", "primary": True},),
        "active": True,
    }
    values.update(overrides)
    return SCIMUserWrite.model_validate(values)


def test_user_schema_is_closed_bounded_and_normalized() -> None:
    resource = user_write()
    assert resource.userName == "analyst@example.com"
    assert resource.displayName == "Example Analyst"
    assert resource.emails[0].value == "analyst@example.com"
    with pytest.raises(ValidationError):
        user_write(password="must-not-enter-the-boundary")
    with pytest.raises(ValidationError):
        user_write(schemas=(SCIM_USER_SCHEMA, SCIM_USER_SCHEMA))


def test_scim_models_accept_real_json_array_shapes() -> None:
    resource = SCIMUserWrite.model_validate(
        {
            "schemas": [SCIM_USER_SCHEMA],
            "externalId": "json-user",
            "userName": "json@example.com",
            "emails": [{"value": "json@example.com", "primary": True}],
        }
    )
    group = SCIMGroupWrite.model_validate(
        {
            "schemas": [SCIM_GROUP_SCHEMA],
            "externalId": "json-group",
            "displayName": "JSON Group",
            "members": [{"value": "scu-0123456789abcdef0123456789abcdef"}],
        }
    )
    assert resource.schemas == (SCIM_USER_SCHEMA,)
    assert group.members[0].value.startswith("scu-")


@pytest.mark.parametrize("username", ["", "UPPER SPACE", "x" * 161, "../escape"])
def test_user_rejects_hostile_usernames(username: str) -> None:
    with pytest.raises(ValidationError):
        user_write(userName=username)


def test_user_rejects_multiple_primary_emails_and_control_characters() -> None:
    with pytest.raises(ValidationError):
        user_write(emails=({"value": "a@example.com", "primary": True}, {"value": "b@example.com", "primary": True}))
    with pytest.raises(ValidationError):
        user_write(externalId="bad\nvalue")


def test_user_create_is_domain_scoped_and_external_id_idempotent() -> None:
    repository, audit = MemoryRepository(), Audit()
    service = SCIMService(repository, audit)
    first, created = service.provision_user(tenant_id="tenant-a", provisioning_domain="idp-a", actor_id="scim-a", resource=user_write())
    second, created_again = service.provision_user(tenant_id="tenant-a", provisioning_domain="idp-a", actor_id="scim-a", resource=user_write())
    other, other_created = service.provision_user(tenant_id="tenant-a", provisioning_domain="idp-b", actor_id="scim-b", resource=user_write())
    assert (created, created_again, other_created) == (True, False, True)
    assert first.id == second.id and other.id != first.id
    assert [event["action"] for event in audit.events] == ["CREATE", "REPLACE", "CREATE"]


def test_deactivation_is_scoped_and_audited_without_deleting_identity() -> None:
    repository, audit = MemoryRepository(), Audit()
    service = SCIMService(repository, audit)
    user, _ = service.provision_user(tenant_id="tenant-a", provisioning_domain="idp-a", actor_id="scim-a", resource=user_write())
    disabled = service.deactivate_user(tenant_id="tenant-a", provisioning_domain="idp-a", actor_id="scim-a", resource_id=user.id)
    assert disabled.active is False
    assert disabled.version == 2
    assert audit.events[-1]["action"] == "DEACTIVATE"
    with pytest.raises(SCIMError):
        service.deactivate_user(tenant_id="tenant-a", provisioning_domain="idp-b", actor_id="scim-b", resource_id=user.id)
    assert audit.events[-1]["outcome"] == "DENIED"


def test_group_membership_is_bounded_deduplicated_and_domain_scoped() -> None:
    repository, audit = MemoryRepository(), Audit()
    service = SCIMService(repository, audit)
    user, _ = service.provision_user(tenant_id="tenant-a", provisioning_domain="idp-a", actor_id="scim-a", resource=user_write())
    group_resource = SCIMGroupWrite.model_validate({
        "schemas": (SCIM_GROUP_SCHEMA,), "externalId": "finance", "displayName": "Finance", "members": ({"value": user.id},)
    })
    group, created = service.provision_group(tenant_id="tenant-a", provisioning_domain="idp-a", actor_id="scim-a", resource=group_resource)
    assert created and group.member_ids == (user.id,)
    with pytest.raises(ValidationError):
        SCIMGroupWrite.model_validate({
            "schemas": (SCIM_GROUP_SCHEMA,), "externalId": "duplicate", "displayName": "Duplicate", "members": ({"value": user.id}, {"value": user.id})
        })
    with pytest.raises(SCIMError):
        service.provision_group(tenant_id="tenant-a", provisioning_domain="idp-b", actor_id="scim-b", resource=group_resource)


def test_scim_groups_do_not_model_reconforge_roles_or_permissions() -> None:
    fields = SCIMGroupWrite.model_fields
    assert "roles" not in fields and "permissions" not in fields
    with pytest.raises(ValidationError):
        SCIMGroupWrite.model_validate({
            "schemas": (SCIM_GROUP_SCHEMA,), "externalId": "finance", "displayName": "Finance", "roles": ["admin"]
        })


def test_timestamp_is_deterministic_utc() -> None:
    assert scim_timestamp(datetime(2026, 7, 28, 3, 4, 5)) == "2026-07-28T03:04:05Z"
