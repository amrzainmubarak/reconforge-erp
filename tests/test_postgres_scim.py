from __future__ import annotations

import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any

import pytest

from reconforge.auth.scim import SCIM_GROUP_SCHEMA, SCIM_USER_SCHEMA, SCIMGroupWrite, SCIMService, SCIMUserWrite
from reconforge.infrastructure.postgres_scim import (
    POSTGRES_SCIM_SCHEMA_SQL,
    PostgresSCIMAuditSink,
    PostgresSCIMRepository,
    scim_resource_etag,
)


class Cursor:
    def fetchone(self) -> None:
        return None


class AuditConnection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...] | None]] = []

    def execute(self, sql: str, parameters: tuple[Any, ...] | None = None) -> Cursor:
        self.calls.append((sql, parameters))
        return Cursor()


def _user(
    external_id: str = "employee-42", *, display: str = "Example Analyst", active: bool = True
) -> SCIMUserWrite:
    return SCIMUserWrite.model_validate(
        {
            "schemas": [SCIM_USER_SCHEMA],
            "externalId": external_id,
            "userName": f"{external_id}@example.test",
            "displayName": display,
            "emails": [{"value": f"{external_id}@example.test", "primary": True}],
            "active": active,
        }
    )


def test_schema_forces_rls_and_keeps_scim_groups_out_of_rbac() -> None:
    assert POSTGRES_SCIM_SCHEMA_SQL.count("FORCE ROW LEVEL SECURITY") == 4
    assert "UNIQUE (tenant_id, provisioning_domain, external_id)" in POSTGRES_SCIM_SCHEMA_SQL
    assert "REFERENCES reconforge.identity_users" in POSTGRES_SCIM_SCHEMA_SQL
    assert "REFERENCES reconforge.scim_users" in POSTGRES_SCIM_SCHEMA_SQL
    assert "identity_user_roles" not in POSTGRES_SCIM_SCHEMA_SQL
    assert "identity_role_permissions" not in POSTGRES_SCIM_SCHEMA_SQL
    assert "password" not in POSTGRES_SCIM_SCHEMA_SQL


def test_audit_sink_persists_only_bounded_lifecycle_metadata() -> None:
    connection = AuditConnection()
    PostgresSCIMAuditSink(connection).record(
        tenant_id="tenant-a",
        domain="idp-a",
        actor_id="scim-client",
        resource_type="User",
        resource_id="scu-0123456789abcdef0123456789abcdef",
        action="DEACTIVATE",
        outcome="ALLOWED",
        reason_code=None,
    )
    _, values = connection.calls[-1]
    assert values is not None
    assert values[0] == "tenant-a"
    assert values[2:] == (
        "idp-a",
        "scim-client",
        "User",
        "scu-0123456789abcdef0123456789abcdef",
        "DEACTIVATE",
        "ALLOWED",
        None,
    )
    assert "example.test" not in repr(values)


def test_etag_is_versioned_weak_and_does_not_reveal_external_id() -> None:
    from reconforge.auth.scim import SCIMUser

    resource = SCIMUser(
        id="scu-0123456789abcdef0123456789abcdef",
        provisioning_domain="idp-a",
        external_id="sensitive-external-id",
        username="analyst@example.test",
        display_name="Analyst",
        email="analyst@example.test",
        active=True,
        version=3,
        created_at=datetime(2026, 7, 28, tzinfo=UTC),
        updated_at=datetime(2026, 7, 28, tzinfo=UTC),
    )
    etag = scim_resource_etag(resource)
    assert etag.startswith('W/"') and etag.endswith('"')
    assert "sensitive" not in etag and resource.id not in etag


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires live PostgreSQL service")
def test_live_postgres_scim_idempotency_deactivation_sessions_and_rls() -> None:
    pytest.importorskip("psycopg")
    from reconforge.infrastructure.postgres import (
        PostgresConnectionFactory,
        PostgresSettings,
        PostgresTenantBoundary,
        install_postgres_rls_schema,
    )
    from reconforge.infrastructure.postgres_identity import POSTGRES_IDENTITY_SCHEMA_SQL, PostgresIdentityRepository

    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if app_user and not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", app_user):
        pytest.fail("RECONFORGE_TEST_POSTGRES_APP_USER contains unsafe characters")
    factory = PostgresConnectionFactory(PostgresSettings(dsn=dsn, require_tls=False))
    admin_factory = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False))
    admin = admin_factory.connect()
    tenant_a, tenant_b = "scim_live_a", "scim_live_b"
    try:
        with admin.transaction():
            install_postgres_rls_schema(admin)
            admin.execute(POSTGRES_IDENTITY_SCHEMA_SQL)
            admin.execute(POSTGRES_SCIM_SCHEMA_SQL)
            _cleanup(admin, tenant_a, tenant_b)
            if app_user:
                admin.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
                admin.execute(
                        f"GRANT SELECT, INSERT, UPDATE, DELETE ON reconforge.tenants, "
                        f"reconforge.identity_users, reconforge.identity_sessions, reconforge.identity_user_roles, "
                    f"reconforge.scim_users, reconforge.scim_groups, "
                    f"reconforge.scim_group_members, reconforge.scim_events TO {app_user}"
                )
        for tenant in (tenant_a, tenant_b):
            with PostgresTenantBoundary(factory).transaction(tenant) as connection:
                connection.execute(
                    "INSERT INTO reconforge.tenants (id, name) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                    (tenant, tenant),
                )
        def provision_once() -> tuple[Any, bool]:
            with PostgresTenantBoundary(factory).transaction(tenant_a) as connection:
                return SCIMService(PostgresSCIMRepository(connection), PostgresSCIMAuditSink(connection)).provision_user(
                    tenant_id=tenant_a,
                    provisioning_domain="corp-idp",
                    actor_id="scim-client",
                    resource=_user(),
                )

        with ThreadPoolExecutor(max_workers=2) as executor:
            concurrent_results = list(executor.map(lambda _: provision_once(), range(2)))
        assert sorted(created for _, created in concurrent_results) == [False, True]
        assert len({resource.id for resource, _ in concurrent_results}) == 1
        assert {resource.version for resource, _ in concurrent_results} == {1}
        with PostgresTenantBoundary(factory).transaction(tenant_a) as connection:
            repository = PostgresSCIMRepository(connection)
            audit = PostgresSCIMAuditSink(connection)
            service = SCIMService(repository, audit)
            first, created = service.provision_user(
                tenant_id=tenant_a,
                provisioning_domain="corp-idp",
                actor_id="scim-client",
                resource=_user(),
            )
            repeated, repeated_created = service.provision_user(
                tenant_id=tenant_a,
                provisioning_domain="corp-idp",
                actor_id="scim-client",
                resource=_user(),
            )
            assert not created and not repeated_created
            assert (first.id, first.version) == (repeated.id, repeated.version) == (first.id, 1)
            changed, _ = service.provision_user(
                tenant_id=tenant_a,
                provisioning_domain="corp-idp",
                actor_id="scim-client",
                resource=_user(display="Changed Analyst"),
            )
            assert changed.id == first.id and changed.version == 2
            group, group_created = service.provision_group(
                tenant_id=tenant_a,
                provisioning_domain="corp-idp",
                actor_id="scim-client",
                resource=SCIMGroupWrite.model_validate(
                    {
                        "schemas": [SCIM_GROUP_SCHEMA],
                        "externalId": "finance-reviewers",
                        "displayName": "Finance Reviewers",
                        "members": [{"value": first.id}],
                    }
                ),
            )
            assert group_created and group.member_ids == (first.id,)
            repeated_group, repeated_group_created = service.provision_group(
                tenant_id=tenant_a,
                provisioning_domain="corp-idp",
                actor_id="scim-client",
                resource=SCIMGroupWrite.model_validate(
                    {
                        "schemas": [SCIM_GROUP_SCHEMA],
                        "externalId": "finance-reviewers",
                        "displayName": "Finance Reviewers",
                        "members": [{"value": first.id}],
                    }
                ),
            )
            assert not repeated_group_created and repeated_group.version == group.version == 1
            identity = PostgresIdentityRepository(connection)
            session = identity.create_session(tenant_id=tenant_a, user_id=first.id)
            assert identity.authenticate_token(tenant_id=tenant_a, token=session.token) is not None
            disabled = service.deactivate_user(
                tenant_id=tenant_a,
                provisioning_domain="corp-idp",
                actor_id="scim-client",
                resource_id=first.id,
            )
            assert not disabled.active and disabled.version == 3
            assert identity.authenticate_token(tenant_id=tenant_a, token=session.token) is None
            state = connection.execute(
                """SELECT disabled,disabled_at,disabled_by,lifecycle_version
                     FROM reconforge.identity_users WHERE tenant_id=%s AND id=%s""",
                (tenant_a, first.id),
            ).fetchone()
            assert state is not None and bool(state[0]) and state[1] is not None
            assert state[2] == "scim:corp-idp" and state[3] == 2
            session_state = connection.execute(
                """SELECT revocation_reason_code,revoked_by,lifecycle_version
                     FROM reconforge.identity_sessions WHERE tenant_id=%s AND id=%s""",
                (tenant_a, session.id),
            ).fetchone()
            assert session_state is not None
            assert tuple(session_state) == ("scim_deactivation", first.id, 2)
            enabled, enabled_created = service.provision_user(
                tenant_id=tenant_a,
                provisioning_domain="corp-idp",
                actor_id="scim-client",
                resource=_user(display="Changed Analyst"),
            )
            assert not enabled_created and enabled.active and enabled.version == 4
            enabled_state = connection.execute(
                """SELECT disabled,disabled_at,disabled_by,lifecycle_version
                     FROM reconforge.identity_users WHERE tenant_id=%s AND id=%s""",
                (tenant_a, first.id),
            ).fetchone()
            assert enabled_state is not None
            assert tuple(enabled_state) == (False, None, None, 3)
            inactive, inactive_created = service.provision_user(
                tenant_id=tenant_a,
                provisioning_domain="corp-idp",
                actor_id="scim-client",
                resource=_user("inactive-43", display="Inactive Analyst", active=False),
            )
            assert inactive_created and not inactive.active
            inactive_state = connection.execute(
                """SELECT disabled,(disabled_at IS NOT NULL),disabled_by,lifecycle_version
                     FROM reconforge.identity_users WHERE tenant_id=%s AND id=%s""",
                (tenant_a, inactive.id),
            ).fetchone()
            assert inactive_state is not None
            assert tuple(inactive_state) == (True, True, "scim:corp-idp", 1)
            assert connection.execute("SELECT count(*) FROM reconforge.identity_user_roles").fetchone()[0] == 0
        with PostgresTenantBoundary(factory).transaction(tenant_b) as connection:
            assert connection.execute("SELECT count(*) FROM reconforge.scim_users").fetchone()[0] == 0
            assert connection.execute("SELECT count(*) FROM reconforge.scim_groups").fetchone()[0] == 0
            assert connection.execute("SELECT count(*) FROM reconforge.scim_events").fetchone()[0] == 0
    finally:
        try:
            with admin.transaction():
                _cleanup(admin, tenant_a, tenant_b)
        finally:
            admin.close()


def _cleanup(connection: Any, tenant_a: str, tenant_b: str) -> None:
    tenants = (tenant_a, tenant_b)
    connection.execute("DELETE FROM reconforge.scim_group_members WHERE tenant_id IN (%s, %s)", tenants)
    connection.execute("DELETE FROM reconforge.scim_events WHERE tenant_id IN (%s, %s)", tenants)
    connection.execute("DELETE FROM reconforge.scim_groups WHERE tenant_id IN (%s, %s)", tenants)
    connection.execute("DELETE FROM reconforge.scim_users WHERE tenant_id IN (%s, %s)", tenants)
    connection.execute("DELETE FROM reconforge.tenants WHERE id IN (%s, %s)", tenants)
