from __future__ import annotations

import os
import re
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.api.scim_security import SCIMRequestContext, get_scim_context
from reconforge.auth.scim import (
    SCIM_GROUP_SCHEMA,
    SCIM_USER_SCHEMA,
    SCIMError,
    SCIMGroup,
    SCIMGroupWrite,
    SCIMUser,
    SCIMUserWrite,
)
from reconforge.infrastructure.postgres_scim_auth import SCIMClientPrincipal


class Repository:
    def __init__(self) -> None:
        self.users: dict[str, SCIMUser] = {}
        self.user_external: dict[str, str] = {}
        self.groups: dict[str, SCIMGroup] = {}
        self.group_external: dict[str, str] = {}
        self.now = datetime(2026, 7, 28, tzinfo=UTC)

    def put_user(self, *, tenant_id: str, domain: str, resource: SCIMUserWrite) -> tuple[SCIMUser, bool]:
        del tenant_id
        identifier = self.user_external.get(resource.externalId)
        created = identifier is None
        current = self.users.get(identifier or "")
        identifier = identifier or f"scu-{len(self.users) + 1:032x}"
        email = resource.emails[0].value if resource.emails else None
        state = (resource.userName, resource.displayName or resource.userName, email, resource.active)
        if current is not None and state == (current.username, current.display_name, current.email, current.active):
            return current, False
        user = SCIMUser(
            identifier,
            domain,
            resource.externalId,
            state[0],
            state[1],
            state[2],
            state[3],
            1 if current is None else current.version + 1,
            self.now if current is None else current.created_at,
            self.now,
        )
        self.users[identifier] = user
        self.user_external[resource.externalId] = identifier
        return user, created

    def get_user(self, *, tenant_id: str, domain: str, resource_id: str, for_update: bool = False) -> SCIMUser:
        del tenant_id, for_update
        value = self.users.get(resource_id)
        if value is None or value.provisioning_domain != domain:
            raise SCIMError("SCIM User was not found.")
        return value

    def list_users(
        self,
        *,
        tenant_id: str,
        domain: str,
        filter_attribute: str | None,
        filter_value: str | None,
        offset: int,
        limit: int,
    ) -> tuple[int, tuple[SCIMUser, ...]]:
        del tenant_id
        values = [item for item in self.users.values() if item.provisioning_domain == domain]
        if filter_attribute == "username":
            values = [item for item in values if item.username == filter_value]
        elif filter_attribute == "externalid":
            values = [item for item in values if item.external_id == filter_value]
        values.sort(key=lambda item: item.id)
        return len(values), tuple(values[offset : offset + limit])

    def replace_user(
        self, *, tenant_id: str, domain: str, resource_id: str, expected_version: int, resource: SCIMUserWrite
    ) -> SCIMUser:
        current = self.get_user(tenant_id=tenant_id, domain=domain, resource_id=resource_id)
        if current.version != expected_version:
            raise SCIMError("SCIM resource version does not match.", scim_type="invalidVers")
        updated, _ = self.put_user(tenant_id=tenant_id, domain=domain, resource=resource)
        return updated

    def set_user_active(self, *, tenant_id: str, domain: str, resource_id: str, active: bool) -> SCIMUser:
        current = self.get_user(tenant_id=tenant_id, domain=domain, resource_id=resource_id)
        updated = replace(current, active=active, version=current.version + (current.active != active))
        self.users[resource_id] = updated
        return updated

    def put_group(self, *, tenant_id: str, domain: str, resource: SCIMGroupWrite) -> tuple[SCIMGroup, bool]:
        del tenant_id
        members = tuple(sorted(member.value for member in resource.members))
        if any(member not in self.users or self.users[member].provisioning_domain != domain for member in members):
            raise SCIMError("SCIM Group contains an unknown member.")
        identifier = self.group_external.get(resource.externalId)
        created = identifier is None
        current = self.groups.get(identifier or "")
        identifier = identifier or f"scg-{len(self.groups) + 1:032x}"
        if current is not None and (current.display_name, current.member_ids) == (resource.displayName, members):
            return current, False
        group = SCIMGroup(
            identifier,
            domain,
            resource.externalId,
            resource.displayName,
            members,
            1 if current is None else current.version + 1,
            self.now if current is None else current.created_at,
            self.now,
        )
        self.groups[identifier] = group
        self.group_external[resource.externalId] = identifier
        return group, created

    def get_group(self, *, tenant_id: str, domain: str, resource_id: str, for_update: bool = False) -> SCIMGroup:
        del tenant_id, for_update
        value = self.groups.get(resource_id)
        if value is None or value.provisioning_domain != domain:
            raise SCIMError("SCIM Group was not found.")
        return value

    def list_groups(
        self,
        *,
        tenant_id: str,
        domain: str,
        filter_attribute: str | None,
        filter_value: str | None,
        offset: int,
        limit: int,
    ) -> tuple[int, tuple[SCIMGroup, ...]]:
        del tenant_id
        values = [item for item in self.groups.values() if item.provisioning_domain == domain]
        if filter_attribute == "displayname":
            values = [item for item in values if item.display_name == filter_value]
        elif filter_attribute == "externalid":
            values = [item for item in values if item.external_id == filter_value]
        values.sort(key=lambda item: item.id)
        return len(values), tuple(values[offset : offset + limit])

    def replace_group(
        self, *, tenant_id: str, domain: str, resource_id: str, expected_version: int, resource: SCIMGroupWrite
    ) -> SCIMGroup:
        current = self.get_group(tenant_id=tenant_id, domain=domain, resource_id=resource_id)
        if current.version != expected_version:
            raise SCIMError("SCIM resource version does not match.", scim_type="invalidVers")
        updated, _ = self.put_group(tenant_id=tenant_id, domain=domain, resource=resource)
        return updated

    def delete_group(self, *, tenant_id: str, domain: str, resource_id: str, expected_version: int) -> SCIMGroup:
        current = self.get_group(tenant_id=tenant_id, domain=domain, resource_id=resource_id)
        if current.version != expected_version:
            raise SCIMError("SCIM resource version does not match.", scim_type="invalidVers")
        del self.groups[resource_id]
        return current


class Audit:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def record(self, **event: Any) -> None:
        self.events.append(event)


def _client(tmp_path: Path) -> tuple[TestClient, Repository, Audit]:
    app = create_api_app(tmp_path / "unused.db")
    repository, audit = Repository(), Audit()
    context = SCIMRequestContext(
        SCIMClientPrincipal("tenant-a", "corp-idp", "scim-client", "credential-a"), repository, audit
    )  # type: ignore[arg-type]
    app.dependency_overrides[get_scim_context] = lambda: context
    return TestClient(app), repository, audit


def _user() -> dict[str, Any]:
    return {
        "schemas": [SCIM_USER_SCHEMA],
        "externalId": "employee-42",
        "userName": "analyst@example.test",
        "displayName": "Example Analyst",
        "emails": [{"value": "analyst@example.test", "primary": True}],
        "active": True,
    }


def test_scim_is_disabled_by_default_and_uses_protocol_error_shape(tmp_path: Path) -> None:
    response = TestClient(create_api_app(tmp_path / "unused.db")).get("/scim/v2/ServiceProviderConfig")
    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/scim+json")
    assert response.json()["schemas"] == ["urn:ietf:params:scim:api:messages:2.0:Error"]


def test_discovery_is_authenticated_and_truthfully_bounded(tmp_path: Path) -> None:
    client, _, _ = _client(tmp_path)
    config = client.get("/scim/v2/ServiceProviderConfig")
    assert config.status_code == 200
    assert config.json()["patch"]["supported"] is True
    assert config.json()["bulk"]["supported"] is False
    assert config.json()["etag"]["supported"] is True
    assert client.get("/scim/v2/ResourceTypes").json()["totalResults"] == 2
    assert client.get("/scim/v2/Schemas").json()["totalResults"] == 2


def test_user_http_lifecycle_filter_etag_patch_and_deactivation(tmp_path: Path) -> None:
    client, repository, audit = _client(tmp_path)
    created = client.post("/scim/v2/Users", json=_user())
    assert created.status_code == 201
    assert created.headers["content-type"].startswith("application/scim+json")
    user_id, etag = created.json()["id"], created.headers["etag"]
    replay = client.post("/scim/v2/Users", json=_user())
    assert replay.status_code == 200 and replay.json()["id"] == user_id
    filtered = client.get("/scim/v2/Users?filter=userName%20eq%20%22analyst@example.test%22")
    assert filtered.json()["totalResults"] == 1
    stale = client.patch(
        f"/scim/v2/Users/{user_id}",
        headers={"If-Match": 'W/"stale"'},
        json={
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "replace", "path": "active", "value": False}],
        },
    )
    assert stale.status_code == 412 and stale.json()["scimType"] == "invalidVers"
    patched = client.patch(
        f"/scim/v2/Users/{user_id}",
        headers={"If-Match": etag},
        json={
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "replace", "path": "displayName", "value": "Changed Analyst"}],
        },
    )
    assert patched.status_code == 200 and patched.json()["displayName"] == "Changed Analyst"
    deleted = client.delete(f"/scim/v2/Users/{user_id}", headers={"If-Match": patched.headers["etag"]})
    assert deleted.status_code == 204 and repository.users[user_id].active is False
    assert any(event["action"] == "DEACTIVATE" for event in audit.events)


def test_group_http_membership_patch_etag_and_delete(tmp_path: Path) -> None:
    client, _, audit = _client(tmp_path)
    user_id = client.post("/scim/v2/Users", json=_user()).json()["id"]
    created = client.post(
        "/scim/v2/Groups",
        json={"schemas": [SCIM_GROUP_SCHEMA], "externalId": "finance", "displayName": "Finance", "members": []},
    )
    group_id, etag = created.json()["id"], created.headers["etag"]
    added = client.patch(
        f"/scim/v2/Groups/{group_id}",
        headers={"If-Match": etag},
        json={
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "add", "path": "members", "value": [{"value": user_id}]}],
        },
    )
    assert added.status_code == 200 and added.json()["members"][0]["value"] == user_id
    removed = client.patch(
        f"/scim/v2/Groups/{group_id}",
        headers={"If-Match": added.headers["etag"]},
        json={
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "remove", "path": f'members[value eq "{user_id}"]'}],
        },
    )
    assert removed.status_code == 200 and removed.json()["members"] == []
    deleted = client.delete(f"/scim/v2/Groups/{group_id}", headers={"If-Match": removed.headers["etag"]})
    assert deleted.status_code == 204
    assert any(event["action"] == "DELETE" for event in audit.events)


def test_scim_hostile_and_unsupported_inputs_fail_with_scim_errors(tmp_path: Path) -> None:
    client, _, _ = _client(tmp_path)
    hostile = _user() | {"password": "must-not-be-accepted"}
    response = client.post("/scim/v2/Users", json=hostile)
    assert response.status_code == 400 and response.json()["scimType"] == "invalidValue"
    invalid_filter = client.get("/scim/v2/Users?filter=email%20co%20%22secret%22")
    assert invalid_filter.status_code == 400 and invalid_filter.json()["scimType"] == "invalidFilter"


def _cleanup_live(connection: Any, tenant_a: str, tenant_b: str) -> None:
    tenants = (tenant_a, tenant_b)
    connection.execute("DELETE FROM reconforge.scim_group_members WHERE tenant_id IN (%s,%s)", tenants)
    connection.execute("DELETE FROM reconforge.scim_events WHERE tenant_id IN (%s,%s)", tenants)
    connection.execute("DELETE FROM reconforge.scim_groups WHERE tenant_id IN (%s,%s)", tenants)
    connection.execute("DELETE FROM reconforge.scim_users WHERE tenant_id IN (%s,%s)", tenants)
    connection.execute("DELETE FROM reconforge.scim_credentials WHERE tenant_id IN (%s,%s)", tenants)
    connection.execute("DELETE FROM reconforge.tenants WHERE id IN (%s,%s)", tenants)


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires live PostgreSQL service")
def test_live_scim_http_auth_lifecycle_etag_filter_and_tenant_isolation(tmp_path: Path) -> None:
    pytest.importorskip("psycopg")
    from reconforge.infrastructure.postgres import PostgresConnectionFactory, PostgresSettings, PostgresTenantBoundary
    from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository
    from reconforge.infrastructure.postgres_scim_auth import PostgresSCIMCredentialRepository

    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if app_user and not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", app_user):
        pytest.fail("RECONFORGE_TEST_POSTGRES_APP_USER contains unsafe characters")
    factory = PostgresConnectionFactory(PostgresSettings(dsn=dsn, require_tls=False))
    admin_factory = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False))
    admin = admin_factory.connect()
    tenant_a, tenant_b = "scim_http_a", "scim_http_b"
    try:
        with admin.transaction():
            _cleanup_live(admin, tenant_a, tenant_b)
            if app_user:
                admin.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
                admin.execute(
                    f"GRANT SELECT, INSERT, UPDATE, DELETE ON reconforge.tenants, "
                    f"reconforge.identity_users, reconforge.identity_sessions, reconforge.identity_user_roles, "
                    f"reconforge.scim_users, reconforge.scim_groups, reconforge.scim_group_members, "
                    f"reconforge.scim_events, reconforge.scim_credentials TO {app_user}"
                )
        for tenant in (tenant_a, tenant_b):
            with PostgresTenantBoundary(factory).transaction(tenant) as connection:
                connection.execute("INSERT INTO reconforge.tenants (id,name) VALUES (%s,%s)", (tenant, tenant))
        with PostgresTenantBoundary(factory).transaction(tenant_a) as connection:
            issued = PostgresSCIMCredentialRepository(connection).issue(
                tenant_id=tenant_a,
                provisioning_domain="corp-idp",
                client_id="scim-client",
                actor_id="security-admin",
                ttl=timedelta(days=30),
            )
        app = create_api_app(
            tmp_path / "unused.db",
            tenant_db_root=tmp_path / "tenants",
            postgres_dsn=dsn,
            postgres_require_tls=False,
        )
        client = TestClient(app)
        headers = {"Authorization": f"Bearer {issued.token}", "X-ReconForge-Tenant": tenant_a}
        assert client.get("/scim/v2/ServiceProviderConfig", headers=headers).status_code == 200
        assert client.get("/scim/v2/ServiceProviderConfig").status_code == 401
        cross_tenant = {"Authorization": f"Bearer {issued.token}", "X-ReconForge-Tenant": tenant_b}
        assert client.get("/scim/v2/ServiceProviderConfig", headers=cross_tenant).status_code == 401
        created = client.post("/scim/v2/Users", headers=headers, json=_user())
        assert created.status_code == 201
        user_id, etag = created.json()["id"], created.headers["etag"]
        filtered = client.get("/scim/v2/Users?filter=externalId%20eq%20%22employee-42%22", headers=headers)
        assert filtered.json()["totalResults"] == 1
        with PostgresTenantBoundary(factory).transaction(tenant_a) as connection:
            identity = PostgresIdentityRepository(connection)
            session = identity.create_session(tenant_id=tenant_a, user_id=user_id)
            assert identity.authenticate_token(tenant_id=tenant_a, token=session.token) is not None
        stale = client.patch(
            f"/scim/v2/Users/{user_id}",
            headers=headers | {"If-Match": 'W/"stale"'},
            json={
                "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
                "Operations": [{"op": "replace", "path": "active", "value": False}],
            },
        )
        assert stale.status_code == 412
        deleted = client.delete(f"/scim/v2/Users/{user_id}", headers=headers | {"If-Match": etag})
        assert deleted.status_code == 204
        with PostgresTenantBoundary(factory).transaction(tenant_a) as connection:
            identity = PostgresIdentityRepository(connection)
            assert identity.authenticate_token(tenant_id=tenant_a, token=session.token) is None
            assert connection.execute("SELECT count(*) FROM reconforge.identity_user_roles").fetchone()[0] == 0
            assert (
                connection.execute(
                    "SELECT count(*) FROM reconforge.scim_events WHERE actor_id='scim-client'"
                ).fetchone()[0]
                >= 2
            )
        with PostgresTenantBoundary(factory).transaction(tenant_b) as connection:
            assert connection.execute("SELECT count(*) FROM reconforge.scim_users").fetchone()[0] == 0
            assert connection.execute("SELECT count(*) FROM reconforge.scim_events").fetchone()[0] == 0
    finally:
        try:
            with admin.transaction():
                _cleanup_live(admin, tenant_a, tenant_b)
        finally:
            admin.close()
