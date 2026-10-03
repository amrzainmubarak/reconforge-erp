"""Live PostgreSQL inbox acceptance in an independently owned disposable database."""

from __future__ import annotations

import os
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient

from alembic import command
from reconforge.api import create_api_app
from reconforge.api.routes.notification_inbox import router
from reconforge.application.notification_inbox import NotificationInboxService
from reconforge.domain.notification_inbox import (
    InboxConflictError,
    InboxError,
    InboxNotFoundError,
    InboxPersistenceError,
    InboxPublication,
    InboxScope,
    InboxTopic,
)
from reconforge.infrastructure.notification_inbox_schema import POSTGRES_NOTIFICATION_INBOX_SQL
from reconforge.infrastructure.postgres import PostgresConnectionFactory, PostgresSettings, PostgresTenantBoundary
from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository
from reconforge.infrastructure.postgres_notification_inbox import PostgresNotificationInboxRepository
from reconforge.infrastructure.postgres_scope_authority import PostgresScopeAuthorityRepository

pytestmark = pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="PG-INBOX-ENV: live PostgreSQL acceptance requires application/admin DSNs; ADR0825")


def _database_dsn(dsn: str, database: str) -> str:
    parts = urlsplit(dsn)
    return urlunsplit((parts.scheme, parts.netloc, "/" + database, parts.query, parts.fragment))


@pytest.fixture(scope="module")
def database():
    import psycopg
    from psycopg import sql
    admin_dsn = os.environ["RECONFORGE_TEST_POSTGRES_ADMIN_DSN"]
    app_dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    role = os.environ["RECONFORGE_TEST_POSTGRES_APP_USER"]
    assert re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", role)
    name = "amr_inbox_" + uuid4().hex
    assert re.fullmatch(r"amr_inbox_[0-9a-f]{32}", name)
    bootstrap = psycopg.connect(admin_dsn, autocommit=True)
    bootstrap.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    original = os.environ.get("RECONFORGE_POSTGRES_DSN")
    isolated_admin = _database_dsn(admin_dsn, name)
    isolated_app = _database_dsn(app_dsn, name)
    admin_factory = PostgresConnectionFactory(PostgresSettings(dsn=isolated_admin, require_tls=False))
    app_factory = PostgresConnectionFactory(PostgresSettings(dsn=isolated_app, require_tls=False))
    try:
        os.environ["RECONFORGE_POSTGRES_DSN"] = isolated_admin
        command.upgrade(Config("alembic.ini"), "0100_pg_inventory_receipt")
        admin = admin_factory.connect()
        try:
            with admin.transaction():
                admin.execute(POSTGRES_NOTIFICATION_INBOX_SQL)
                admin.execute(sql.SQL("GRANT USAGE ON SCHEMA reconforge TO {}").format(sql.Identifier(role)))
                admin.execute(sql.SQL("GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA reconforge TO {}").format(sql.Identifier(role)))
                admin.execute(sql.SQL("GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA reconforge TO {}").format(sql.Identifier(role)))
        finally:
            admin.close()
        yield admin_factory, app_factory, isolated_app
    finally:
        if original is None:
            os.environ.pop("RECONFORGE_POSTGRES_DSN", None)
        else:
            os.environ["RECONFORGE_POSTGRES_DSN"] = original
        bootstrap.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
        bootstrap.close()


@pytest.fixture
def seeded(database):
    admin_factory, app_factory, app_dsn = database
    tenant = "inbox_" + uuid4().hex[:16]
    publisher, recipient, other = "publisher", "recipient", "other"
    admin = admin_factory.connect()
    try:
        with admin.transaction():
            admin.execute("INSERT INTO reconforge.tenants(id,name) VALUES(%s,%s)", (tenant, tenant))
            for workspace in ("work-a", "work-b"):
                admin.execute("INSERT INTO reconforge.domain_workspaces(tenant_id,id,name) VALUES(%s,%s,%s)", (tenant, workspace, workspace))
            identity = PostgresIdentityRepository(admin)
            for role in ("admin", "reviewer"):
                identity.create_role(tenant_id=tenant, role_name=role)
            for permission in ("notifications.read", "notifications.publish"):
                identity.create_permission(tenant_id=tenant, permission_name=permission)
                identity.grant_permission(tenant_id=tenant, role_name="admin", permission_name=permission)
            identity.grant_permission(tenant_id=tenant, role_name="reviewer", permission_name="notifications.read")
            for actor in (publisher, recipient, other):
                identity.create_user(tenant_id=tenant, user_id=actor, username=actor, password="Synthetic-123", role_name="admin" if actor == publisher else "reviewer")
                PostgresScopeAuthorityRepository(admin).grant(tenant_id=tenant, grant_id="grant-" + actor, principal_type="user", principal_id=actor, scope_type="workspace", scope_id="work-a", actor_id=publisher)
        yield admin, app_factory, app_dsn, InboxScope(tenant, "work-a"), publisher, recipient, other
    finally:
        admin.close()


def _service(connection) -> NotificationInboxService:
    return NotificationInboxService(PostgresNotificationInboxRepository(connection))


def _command(scope: InboxScope, recipient: str, key: str = "publish-1") -> InboxPublication:
    return InboxPublication(scope, recipient, InboxTopic.JOB_FAILED, "job", "JOB-1", key)


def test_live_concurrent_inbox_has_one_publication_ack_audit_and_outbox(seeded) -> None:
    admin, factory, _, scope, publisher, recipient, _ = seeded
    publication = _command(scope, recipient)
    def publish(_: int):
        with PostgresTenantBoundary(factory).transaction(scope.tenant_id, workspace_id=scope.workspace_id) as connection:
            record, created = _service(connection).publish(publication, actor_id=publisher)
            return record.id, created
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(publish, range(16)))
    assert len({item[0] for item in results}) == 1 and sum(item[1] for item in results) == 1
    notification_id = results[0][0]
    def read(_: int):
        with PostgresTenantBoundary(factory).transaction(scope.tenant_id, workspace_id=scope.workspace_id) as connection:
            return _service(connection).acknowledge(scope, actor_id=recipient, notification_id=notification_id).read_at
    with ThreadPoolExecutor(max_workers=8) as executor:
        reads = list(executor.map(read, range(16)))
    assert len(set(reads)) == 1 and reads[0]
    for table in ("domain_audit_events", "outbox_events"):
        column = "object_type" if table == "domain_audit_events" else "aggregate_type"
        count = admin.execute(f"SELECT COUNT(*) FROM reconforge.{table} WHERE tenant_id=%s AND {column}='notification_inbox'", (scope.tenant_id,)).fetchone()[0]
        assert count == 2
    admin.rollback()


def test_live_inbox_rls_revalidation_replay_conflict_and_immutable_evidence(seeded) -> None:
    import psycopg
    admin, factory, _, scope, publisher, recipient, other = seeded
    publication = _command(scope, recipient)
    with PostgresTenantBoundary(factory).transaction(scope.tenant_id, workspace_id=scope.workspace_id) as connection:
        service = _service(connection)
        record, _ = service.publish(publication, actor_id=publisher)
        self_record, _ = service.publish(
            InboxPublication(scope, publisher, InboxTopic.JOB_FAILED, "job", "SELF-1", "self-publish-1"),
            actor_id=publisher,
        )
        assert service.page(scope, actor_id=other).total == 0
        with pytest.raises(InboxNotFoundError):
            service.acknowledge(scope, actor_id=other, notification_id=record.id)
        assert not service.publish(publication, actor_id=publisher)[1]
        with pytest.raises(InboxConflictError):
            service.publish(replace(publication, resource_id="JOB-2"), actor_id=publisher)
        with pytest.raises(InboxError):
            service.publish(replace(publication, scope=InboxScope(scope.tenant_id, "work-b")), actor_id=publisher)
        assert service.page(scope, actor_id=recipient).unread_count == 1
        for query in ("UPDATE reconforge.notification_inbox SET resource_id='JOB-2' WHERE tenant_id=%s", "DELETE FROM reconforge.notification_inbox WHERE tenant_id=%s"):
            with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
                connection.execute(query, (scope.tenant_id,))
    with admin.transaction():
        admin.execute("UPDATE reconforge.principal_scope_grants SET revoked_at=now(),revoked_by=%s,revocation_reason='policy_change' WHERE tenant_id=%s AND principal_id=%s", (publisher, scope.tenant_id, publisher))
    with PostgresTenantBoundary(factory).transaction(scope.tenant_id, workspace_id=scope.workspace_id) as connection:
        connection.execute("SELECT set_config('app.inbox_actor_id',%s,true)", (publisher,))
        connection.execute("SELECT set_config('app.inbox_publish','1',true)")
        with pytest.raises(psycopg.errors.InsufficientPrivilege), connection.transaction():
            connection.execute(
                "INSERT INTO reconforge.notification_inbox_reads(tenant_id,workspace_id,notification_id,recipient_id,read_at) VALUES(%s,%s,%s,%s,now())",
                (scope.tenant_id, scope.workspace_id, self_record.id, publisher),
            )
    with admin.transaction():
        admin.execute("UPDATE reconforge.principal_scope_grants SET revoked_at=now(),revoked_by=%s,revocation_reason='policy_change' WHERE tenant_id=%s AND principal_id=%s", (publisher, scope.tenant_id, recipient))
    with PostgresTenantBoundary(factory).transaction(scope.tenant_id, workspace_id=scope.workspace_id) as connection:
        connection.execute("SELECT set_config('app.inbox_actor_id',%s,true)", (recipient,))
        assert connection.execute("SELECT COUNT(*) FROM reconforge.notification_inbox").fetchone()[0] == 0
        with pytest.raises(InboxError):
            _service(connection).page(scope, actor_id=recipient)


def test_live_api_authentication_scope_and_recipient_permissions(seeded, tmp_path: Path) -> None:
    _, _, dsn, scope, _, recipient, _ = seeded
    app = create_api_app(tmp_path / "legacy.db", tenant_db_root=tmp_path / "tenants", postgres_dsn=dsn, postgres_require_tls=False)
    if not any(getattr(route, "path", "") == "/api/v1/notifications/inbox" for route in app.routes):
        app.include_router(router, prefix="/api/v1")
    with TestClient(app) as client:
        def headers(username: str):
            login = client.post("/api/v1/auth/login", headers={"X-ReconForge-Tenant": scope.tenant_id}, json={"username": username, "password": "Synthetic-123"})
            assert login.status_code == 200, login.text
            return {"X-ReconForge-Tenant": scope.tenant_id, "X-ReconForge-Workspace": scope.workspace_id, "Authorization": "Bearer " + login.json()["access_token"]}
        publisher_headers, recipient_headers = headers("publisher"), headers("recipient")
        payload = {"recipient_id": recipient, "topic": "evidence.available", "resource_type": "evidence", "resource_id": "EVIDENCE-1", "idempotency_key": "api-1"}
        assert client.post("/api/v1/notifications/inbox", headers=recipient_headers, json=payload).status_code == 403
        assert client.get("/api/v1/notifications/workspaces", headers=recipient_headers).json()["workspaces"] == ["work-a"]
        created = client.post("/api/v1/notifications/inbox", headers=publisher_headers, json=payload)
        assert created.status_code == 200, created.text
        notification = created.json()["notification"]
        assert client.get("/api/v1/notifications/inbox", headers=recipient_headers).json()["records"] == [notification]
        assert client.get("/api/v1/notifications/inbox", headers={**recipient_headers, "X-ReconForge-Workspace": "work-b"}).status_code == 403
        assert client.post(f"/api/v1/notifications/inbox/{notification['id']}/read", headers=recipient_headers).json()["read_at"]


def test_live_audit_failure_rolls_back_publication_and_read_evidence(seeded) -> None:
    admin, factory, _, scope, publisher, recipient, _ = seeded
    publication = _command(scope, recipient)
    with admin.transaction():
        admin.execute("CREATE OR REPLACE FUNCTION reconforge.inbox_test_failure() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.object_type='notification_inbox' AND NEW.tenant_id=current_setting('app.inbox_failure_tenant',true) THEN RAISE EXCEPTION 'synthetic audit failure'; END IF; RETURN NEW; END $$")
        admin.execute("CREATE TRIGGER inbox_test_failure BEFORE INSERT ON reconforge.domain_audit_events FOR EACH ROW EXECUTE FUNCTION reconforge.inbox_test_failure()")
    try:
        with PostgresTenantBoundary(factory).transaction(scope.tenant_id, workspace_id=scope.workspace_id) as connection:
            connection.execute("SELECT set_config('app.inbox_failure_tenant',%s,true)", (scope.tenant_id,))
            with pytest.raises(InboxPersistenceError):
                _service(connection).publish(publication, actor_id=publisher)
        assert admin.execute("SELECT COUNT(*) FROM reconforge.notification_inbox WHERE tenant_id=%s", (scope.tenant_id,)).fetchone()[0] == 0
        admin.rollback()
        with PostgresTenantBoundary(factory).transaction(scope.tenant_id, workspace_id=scope.workspace_id) as connection:
            record, _ = _service(connection).publish(publication, actor_id=publisher)
            connection.execute("SELECT set_config('app.inbox_failure_tenant',%s,true)", (scope.tenant_id,))
            with pytest.raises(InboxPersistenceError):
                _service(connection).acknowledge(scope, actor_id=recipient, notification_id=record.id)
        assert admin.execute("SELECT COUNT(*) FROM reconforge.notification_inbox_reads WHERE tenant_id=%s", (scope.tenant_id,)).fetchone()[0] == 0
        admin.rollback()
    finally:
        with admin.transaction():
            admin.execute("DROP TRIGGER inbox_test_failure ON reconforge.domain_audit_events")
            admin.execute("DROP FUNCTION reconforge.inbox_test_failure()")
