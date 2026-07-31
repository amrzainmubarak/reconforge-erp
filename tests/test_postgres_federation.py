from __future__ import annotations

import hashlib
import os
import re
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from reconforge.auth.federation import FederatedPrincipal
from reconforge.infrastructure.postgres_federation import (
    POSTGRES_FEDERATION_SCHEMA_SQL,
    PostgresFederationAuditSink,
    PostgresFederationError,
    PostgresFederationReplayStore,
    PostgresFederationRepository,
)


class Cursor:
    def __init__(self, row: tuple[Any, ...] | None = None, rows: list[tuple[Any, ...]] | None = None) -> None:
        self._row = row
        self._rows = rows or []

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._row

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self._rows


class Connection:
    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple[Any, ...] | None]] = []
        self.replay_available = True
        self.local_roles = [("reviewer",)]
        self.active_challenges = 0

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> Cursor:
        self.executed.append((sql, params))
        normalized = " ".join(sql.split()).lower()
        if "insert into reconforge.federation_assertion_replays" in normalized:
            if self.replay_available:
                self.replay_available = False
                return Cursor((params[2],) if params else None)
            return Cursor(None)
        if "insert into reconforge.federation_login_challenges" in normalized:
            return Cursor((params[5],) if params else None)
        if "select count(*) from reconforge.federation_login_challenges" in normalized:
            return Cursor((self.active_challenges,))
        if "update reconforge.federation_login_challenges" in normalized:
            return Cursor((params[3],) if params else None)
        if "insert into reconforge.federation_identity_links" in normalized:
            return Cursor(("user-a", None))
        if "select links.user_id" in normalized:
            return Cursor(("user-a", False))
        if "select roles.name" in normalized:
            return Cursor(rows=self.local_roles)
        if "update reconforge.federation_identity_links" in normalized:
            return Cursor(("user-a",))
        return Cursor()


def _principal(roles: tuple[str, ...] = ("reviewer",)) -> FederatedPrincipal:
    return FederatedPrincipal(
        provider_id="corp-oidc",
        issuer="https://id.example/oidc",
        subject="sensitive-external-subject",
        roles=roles,
        assertion_id="assertion-id",
    )


def test_schema_forces_tenant_rls_and_stores_only_hashed_external_identity() -> None:
    assert "federation_assertion_replays" in POSTGRES_FEDERATION_SCHEMA_SQL
    assert "federation_login_challenges" in POSTGRES_FEDERATION_SCHEMA_SQL
    assert "federation_identity_links" in POSTGRES_FEDERATION_SCHEMA_SQL
    assert "federation_identity_events" in POSTGRES_FEDERATION_SCHEMA_SQL
    assert POSTGRES_FEDERATION_SCHEMA_SQL.count("FORCE ROW LEVEL SECURITY") == 4
    assert "external_subject_hash" in POSTGRES_FEDERATION_SCHEMA_SQL
    assert "assertion_hash" in POSTGRES_FEDERATION_SCHEMA_SQL
    assert "subject TEXT" not in POSTGRES_FEDERATION_SCHEMA_SQL
    assert "assertion_id TEXT" not in POSTGRES_FEDERATION_SCHEMA_SQL
    assert "reason_code TEXT" in POSTGRES_FEDERATION_SCHEMA_SQL


def test_policy_audit_persists_only_sanitized_outcome_and_reason() -> None:
    connection = Connection()
    PostgresFederationAuditSink(connection, "tenant_a").record(
        action="federation_authenticate",
        provider_id="corp-oidc",
        outcome="denied",
        reason_code="assertion_replayed",
    )
    sql, parameters = connection.executed[-1]
    assert "FEDERATION_AUTHENTICATE" in sql
    assert parameters is not None
    assert parameters[2:] == ("corp-oidc", "DENIED", "assertion_replayed")


def test_replay_consume_is_atomic_hashed_and_one_time() -> None:
    connection = Connection()
    store = PostgresFederationReplayStore(connection, "tenant_a")
    expiry = datetime.now(UTC) + timedelta(minutes=5)

    assert store.consume_once(provider_id="corp-oidc", assertion_id="raw-assertion", expires_at=expiry)
    assert not store.consume_once(provider_id="corp-oidc", assertion_id="raw-assertion", expires_at=expiry)
    parameters = connection.executed[0][1]
    assert parameters is not None
    assert parameters[2] == hashlib.sha256(b"raw-assertion").hexdigest()
    assert "raw-assertion" not in parameters


def test_login_challenge_stores_hashes_and_consumes_atomically() -> None:
    connection = Connection()
    repository = PostgresFederationRepository(connection)
    challenge = repository.issue_challenge(tenant_id="tenant_a", provider_id="corp-oidc", protocol="oidc")

    assert challenge.protocol == "oidc"
    assert challenge.challenge_id and challenge.correlation
    insert_parameters = connection.executed[0][1]
    assert insert_parameters is not None
    assert challenge.challenge_id not in insert_parameters
    assert challenge.correlation not in insert_parameters
    assert repository.consume_challenge(
        tenant_id="tenant_a",
        provider_id="corp-oidc",
        protocol="oidc",
        challenge_id=challenge.challenge_id,
        correlation=challenge.correlation,
    )


def test_login_challenge_capacity_fails_closed_under_serialized_provider_lock() -> None:
    connection = Connection()
    connection.active_challenges = 100
    with pytest.raises(PostgresFederationError, match="capacity"):
        PostgresFederationRepository(connection).issue_challenge(
            tenant_id="tenant_a", provider_id="corp-oidc", protocol="oidc"
        )

    assert any("pg_advisory_xact_lock" in sql for sql, _ in connection.executed)
    assert not any("insert into reconforge.federation_login_challenges" in sql for sql, _ in connection.executed)


def test_link_and_login_bind_only_preassigned_local_roles_and_hash_subject() -> None:
    connection = Connection()
    repository = PostgresFederationRepository(connection)
    principal = _principal()
    repository.link_identity(
        tenant_id="tenant_a",
        principal=principal,
        user_id="user-a",
        actor_id="security-admin",
    )
    session = repository.complete_login(tenant_id="tenant_a", principal=principal)

    assert session.user_id == "user-a"
    assert session.token
    all_parameters = [value for _, params in connection.executed for value in (params or ())]
    assert principal.subject not in all_parameters
    assert principal.issuer not in all_parameters
    assert hashlib.sha256(f"{principal.issuer}\x00{principal.subject}".encode()).hexdigest() in all_parameters
    assert sum("federation_identity_events" in sql for sql, _ in connection.executed) == 2


def test_external_role_cannot_exceed_local_assignment_and_link_can_be_disabled() -> None:
    connection = Connection()
    repository = PostgresFederationRepository(connection)
    connection.local_roles = [("reviewer",)]
    with pytest.raises(PostgresFederationError, match="exceed"):
        repository.complete_login(tenant_id="tenant_a", principal=_principal(("admin",)))
    assert not any("identity_sessions" in sql for sql, _ in connection.executed)
    assert repository.disable_link(
        tenant_id="tenant_a", provider_id="corp-oidc", user_id="user-a", actor_id="security-admin"
    )


def test_naive_replay_expiry_is_rejected_before_sql() -> None:
    connection = Connection()
    with pytest.raises(PostgresFederationError, match="timezone"):
        PostgresFederationReplayStore(connection, "tenant_a").consume_once(
            provider_id="corp-oidc",
            assertion_id="assertion",
            expires_at=datetime(2026, 7, 28),
        )
    assert connection.executed == []


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires live PostgreSQL")
def test_live_postgres_federation_replay_link_session_and_rls() -> None:
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
    tenant_a = "federation_a"
    tenant_b = "federation_b"
    try:
        with admin.transaction():
            install_postgres_rls_schema(admin)
            admin.execute(POSTGRES_IDENTITY_SCHEMA_SQL)
            admin.execute(POSTGRES_FEDERATION_SCHEMA_SQL)
            admin.execute(
                "DELETE FROM reconforge.federation_identity_links WHERE tenant_id IN (%s, %s)",
                (tenant_a, tenant_b),
            )
            admin.execute("DELETE FROM reconforge.tenants WHERE id IN (%s, %s)", (tenant_a, tenant_b))
            if app_user:
                admin.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
                admin.execute(
                    f"GRANT SELECT, INSERT, UPDATE, DELETE ON reconforge.tenants, "
                    f"reconforge.identity_roles, reconforge.identity_permissions, reconforge.identity_users, "
                    f"reconforge.identity_user_roles, reconforge.identity_role_permissions, "
                    f"reconforge.identity_sessions, reconforge.federation_login_challenges, "
                    f"reconforge.federation_assertion_replays, "
                    f"reconforge.federation_identity_links, reconforge.federation_identity_events TO {app_user}"
                )
        for tenant_id in (tenant_a, tenant_b):
            with PostgresTenantBoundary(factory).transaction(tenant_id) as connection:
                connection.execute(
                    "INSERT INTO reconforge.tenants (id, name) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                    (tenant_id, tenant_id),
                )
        with PostgresTenantBoundary(factory).transaction(tenant_a) as connection:
            identity = PostgresIdentityRepository(connection)
            identity.create_role(tenant_id=tenant_a, role_name="reviewer")
            identity.create_user(
                tenant_id=tenant_a,
                user_id="user-a",
                username="federated.user",
                password="Local-fallback-Strong-123",
                role_name="reviewer",
            )
            repository = PostgresFederationRepository(connection)
            principal = _principal()
            repository.link_identity(
                tenant_id=tenant_a, principal=principal, user_id="user-a", actor_id="security-admin"
            )
            replay = PostgresFederationReplayStore(connection, tenant_a)
            expiry = datetime.now(UTC) + timedelta(minutes=5)
            assert replay.consume_once(provider_id=principal.provider_id, assertion_id=principal.assertion_id, expires_at=expiry)
            assert not replay.consume_once(
                provider_id=principal.provider_id, assertion_id=principal.assertion_id, expires_at=expiry
            )
            challenge = repository.issue_challenge(
                tenant_id=tenant_a, provider_id=principal.provider_id, protocol="oidc"
            )
            assert repository.consume_challenge(
                tenant_id=tenant_a,
                provider_id=principal.provider_id,
                protocol="oidc",
                challenge_id=challenge.challenge_id,
                correlation=challenge.correlation,
            )
            assert not repository.consume_challenge(
                tenant_id=tenant_a,
                provider_id=principal.provider_id,
                protocol="oidc",
                challenge_id=challenge.challenge_id,
                correlation=challenge.correlation,
            )
            session = repository.complete_login(tenant_id=tenant_a, principal=principal)
            assert identity.authenticate_token(tenant_id=tenant_a, token=session.token) is not None
            stored = connection.execute(
                "SELECT external_subject_hash FROM reconforge.federation_identity_links WHERE tenant_id=%s",
                (tenant_a,),
            ).fetchone()[0]
            assert stored == hashlib.sha256(f"{principal.issuer}\x00{principal.subject}".encode()).hexdigest()
        with PostgresTenantBoundary(factory).transaction(tenant_b) as connection:
            assert connection.execute("SELECT count(*) FROM reconforge.federation_identity_links").fetchone()[0] == 0
            assert connection.execute("SELECT count(*) FROM reconforge.federation_login_challenges").fetchone()[0] == 0
            assert connection.execute("SELECT count(*) FROM reconforge.federation_assertion_replays").fetchone()[0] == 0
    finally:
        try:
            with admin.transaction():
                admin.execute(
                    "DELETE FROM reconforge.federation_identity_links WHERE tenant_id IN (%s, %s)",
                    (tenant_a, tenant_b),
                )
                admin.execute("DELETE FROM reconforge.tenants WHERE id IN (%s, %s)", (tenant_a, tenant_b))
        finally:
            admin.close()
