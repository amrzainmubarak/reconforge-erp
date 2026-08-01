from __future__ import annotations

import os
import re

import pytest

from reconforge.infrastructure.postgres_emergency_access import (
    EMERGENCY_ELIGIBLE_PERMISSIONS,
    POSTGRES_EMERGENCY_ACCESS_SCHEMA_SQL,
    EmergencyAccessError,
    PostgresEmergencyAccessRepository,
)


class UnusedConnection:
    def execute(self, *_: object, **__: object) -> None:
        raise AssertionError("invalid emergency input must fail before database access")


def test_emergency_schema_is_bounded_forced_rls_and_append_only() -> None:
    assert POSTGRES_EMERGENCY_ACCESS_SCHEMA_SQL.count("FORCE ROW LEVEL SECURITY") == 3
    assert "requested_minutes BETWEEN 5 AND 60" in POSTGRES_EMERGENCY_ACCESS_SCHEMA_SQL
    assert "expires_at <= activated_at + interval '60 minutes'" in POSTGRES_EMERGENCY_ACCESS_SCHEMA_SQL
    assert "emergency evidence is append-only" in POSTGRES_EMERGENCY_ACCESS_SCHEMA_SQL
    assert "requester_user_id = target_user_id" in POSTGRES_EMERGENCY_ACCESS_SCHEMA_SQL
    assert "security.emergency.approve" not in EMERGENCY_ELIGIBLE_PERMISSIONS
    assert "users.manage" not in EMERGENCY_ELIGIBLE_PERMISSIONS


@pytest.mark.parametrize(
    ("target", "permissions", "minutes"),
    [
        ("different-user", {"finance_core.validate"}, 15),
        ("requester", {"users.manage"}, 15),
        ("requester", set(), 15),
        ("requester", {"finance_core.validate"}, 61),
    ],
)
def test_emergency_request_rejects_delegation_forbidden_empty_or_excessive_grants(
    target: str, permissions: set[str], minutes: int
) -> None:
    with pytest.raises(EmergencyAccessError):
        PostgresEmergencyAccessRepository(UnusedConnection()).request_access(
            tenant_id="tenant-a",
            requester_user_id="requester",
            target_user_id=target,
            permissions=permissions,
            reason="Documented synthetic production recovery incident",
            incident_reference="INC-100",
            requested_minutes=minutes,
        )


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires live PostgreSQL service")
def test_live_emergency_access_maker_checker_session_use_end_review_and_rls() -> None:
    pytest.importorskip("psycopg")
    from reconforge.infrastructure.postgres import (
        PostgresConnectionFactory,
        PostgresSettings,
        PostgresTenantBoundary,
        install_postgres_rls_schema,
    )
    from reconforge.infrastructure.postgres_identity import POSTGRES_IDENTITY_SCHEMA_SQL, PostgresIdentityRepository
    from reconforge.infrastructure.postgres_privileged_sessions import (
        POSTGRES_PRIVILEGED_SESSION_SCHEMA_SQL,
        PostgresPrivilegedSessionRepository,
    )

    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if app_user and not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", app_user):
        pytest.fail("RECONFORGE_TEST_POSTGRES_APP_USER contains unsafe characters")
    factory = PostgresConnectionFactory(PostgresSettings(dsn=dsn, require_tls=False))
    admin_factory = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False))
    admin = admin_factory.connect()
    tenant_a, tenant_b = "emergency_a", "emergency_b"
    tables = (
        "emergency_access_events",
        "emergency_access_permissions",
        "emergency_access_requests",
        "identity_step_up_assertions",
        "identity_sessions",
        "identity_user_roles",
        "identity_role_permissions",
        "identity_users",
        "identity_permissions",
        "identity_roles",
    )
    try:
        with admin.transaction():
            install_postgres_rls_schema(admin)
            admin.execute(POSTGRES_IDENTITY_SCHEMA_SQL)
            admin.execute(POSTGRES_PRIVILEGED_SESSION_SCHEMA_SQL)
            admin.execute(POSTGRES_EMERGENCY_ACCESS_SCHEMA_SQL)
            for trigger in (
                "emergency_access_events_append_only",
                "emergency_access_permissions_immutable",
                "emergency_access_requests_no_delete",
                "identity_step_up_assertions_append_only",
            ):
                table = "identity_step_up_assertions" if trigger.startswith("identity") else (
                    "emergency_access_events" if "events" in trigger else (
                        "emergency_access_permissions" if "permissions" in trigger else "emergency_access_requests"
                    )
                )
                admin.execute(f"ALTER TABLE reconforge.{table} DISABLE TRIGGER {trigger}")
            for table in tables:
                admin.execute(
                    f"DELETE FROM reconforge.{table} WHERE tenant_id IN (%s,%s)",  # nosec B608 - fixed allowlist
                    (tenant_a, tenant_b),
                )
            for trigger in (
                "emergency_access_events_append_only",
                "emergency_access_permissions_immutable",
                "emergency_access_requests_no_delete",
                "identity_step_up_assertions_append_only",
            ):
                table = "identity_step_up_assertions" if trigger.startswith("identity") else (
                    "emergency_access_events" if "events" in trigger else (
                        "emergency_access_permissions" if "permissions" in trigger else "emergency_access_requests"
                    )
                )
                admin.execute(f"ALTER TABLE reconforge.{table} ENABLE TRIGGER {trigger}")
            admin.execute("DELETE FROM reconforge.tenants WHERE id IN (%s,%s)", (tenant_a, tenant_b))
            admin.execute(
                "INSERT INTO reconforge.tenants(id,name) VALUES (%s,%s),(%s,%s)",
                (tenant_a, tenant_a, tenant_b, tenant_b),
            )
            if app_user:
                admin.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
                admin.execute(f"GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA reconforge TO {app_user}")
        sessions: dict[str, object] = {}
        with PostgresTenantBoundary(factory).transaction(tenant_a) as connection:
            identity = PostgresIdentityRepository(connection)
            for role in ("requester", "approver", "reviewer"):
                identity.create_role(tenant_id=tenant_a, role_name=role)
            for permission in (
                "finance_core.validate",
                "security.emergency.approve",
                "security.emergency.review",
            ):
                identity.create_permission(tenant_id=tenant_a, permission_name=permission)
            identity.grant_permission(
                tenant_id=tenant_a, role_name="approver", permission_name="security.emergency.approve"
            )
            identity.grant_permission(
                tenant_id=tenant_a, role_name="reviewer", permission_name="security.emergency.review"
            )
            for name in ("requester", "approver", "reviewer"):
                user = identity.create_user(
                    tenant_id=tenant_a,
                    user_id=f"human-{name}",
                    username=name,
                    password="Strong-password-123",
                    role_name=name,
                )
                sessions[name] = identity.create_session(tenant_id=tenant_a, user_id=user.id)
                assurance = PostgresPrivilegedSessionRepository(connection).reauthenticate(
                    tenant_id=tenant_a,
                    token=sessions[name].token,  # type: ignore[attr-defined]
                    user_id=user.id,
                    username=user.username,
                    password="Strong-password-123",
                )
                assert assurance is not None and assurance.step_up_active
            repository = PostgresEmergencyAccessRepository(connection)
            requested = repository.request_access(
                tenant_id=tenant_a,
                requester_user_id="human-requester",
                target_user_id="human-requester",
                permissions={"finance_core.validate"},
                reason="Restore a blocked synthetic financial validation operation",
                incident_reference="INC-EMERGENCY-001",
                requested_minutes=15,
            )
            with pytest.raises(EmergencyAccessError, match="maker-checker"):
                repository.approve(
                    tenant_id=tenant_a,
                    access_id=requested.id,
                    approver_user_id="human-requester",
                    expected_version=requested.version,
                )
            approved = repository.approve(
                tenant_id=tenant_a,
                access_id=requested.id,
                approver_user_id="human-approver",
                expected_version=requested.version,
            )
            with pytest.raises(EmergencyAccessError, match="reauthentication"):
                repository.activate(
                    tenant_id=tenant_a,
                    access_id=approved.id,
                    target_user_id="human-requester",
                    session_id=sessions["requester"].id,  # type: ignore[attr-defined]
                    expected_version=approved.version,
                    step_up_active=False,
                )
            active = repository.activate(
                tenant_id=tenant_a,
                access_id=approved.id,
                target_user_id="human-requester",
                session_id=sessions["requester"].id,  # type: ignore[attr-defined]
                expected_version=approved.version,
                step_up_active=True,
            )
            authority = repository.active_for_session(
                tenant_id=tenant_a,
                token=sessions["requester"].token,  # type: ignore[attr-defined]
                user_id="human-requester",
                session_id=sessions["requester"].id,  # type: ignore[attr-defined]
            )
            assert authority.permissions == frozenset({"finance_core.validate"})
            repository.record_use(
                tenant_id=tenant_a,
                access_id=active.id,
                user_id="human-requester",
                session_id=sessions["requester"].id,  # type: ignore[attr-defined]
                permission="finance_core.validate",
                surface="POST /api/v1/finance-core/entries/entry-1/validate",
                request_id="request-use-1",
            )
            ended = repository.end_access(
                tenant_id=tenant_a,
                access_id=active.id,
                actor_user_id="human-requester",
                expected_version=active.version,
                actor_can_administer=False,
                note="Synthetic incident operation completed safely",
            )
            assert not repository.active_for_session(
                tenant_id=tenant_a,
                token=sessions["requester"].token,  # type: ignore[attr-defined]
                user_id="human-requester",
                session_id=sessions["requester"].id,  # type: ignore[attr-defined]
            ).permissions
            with pytest.raises(EmergencyAccessError, match="independence"):
                repository.review(
                    tenant_id=tenant_a,
                    access_id=ended.id,
                    reviewer_user_id="human-requester",
                    expected_version=ended.version,
                    outcome="Confirmed",
                    note="Requester cannot review their own emergency use",
                )
            reviewed = repository.review(
                tenant_id=tenant_a,
                access_id=ended.id,
                reviewer_user_id="human-reviewer",
                expected_version=ended.version,
                outcome="Confirmed",
                note="Independent review confirmed the bounded synthetic use",
            )
            assert reviewed.status == "Reviewed"
            actions = [row[0] for row in connection.execute(
                "SELECT action FROM reconforge.emergency_access_events ORDER BY event_sequence"
            ).fetchall()]
            assert actions == ["requested", "approved", "activated", "used", "ended", "reviewed"]
            with pytest.raises(Exception, match="append-only"), connection.transaction():
                connection.execute("DELETE FROM reconforge.emergency_access_events")
        with PostgresTenantBoundary(factory).transaction(tenant_b) as connection:
            repository = PostgresEmergencyAccessRepository(connection)
            authority = repository.active_for_session(
                tenant_id=tenant_b,
                token=sessions["requester"].token,  # type: ignore[attr-defined]
                user_id="human-requester",
                session_id=sessions["requester"].id,  # type: ignore[attr-defined]
            )
            assert not authority.permissions
            assert repository.list_access(tenant_id=tenant_b, actor_user_id="human-requester", can_administer=True) == []
    finally:
        admin.close()
