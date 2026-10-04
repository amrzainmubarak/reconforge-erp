"""HTTP and PostgreSQL acceptance for governed exception review."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.api.server_identity import AuthenticatedServerRequest
from reconforge.auth.models import LocalUser
from reconforge.domain.exception_review import ExceptionReviewScope
from reconforge.infrastructure.postgres import (
    PostgresConnectionFactory,
    PostgresSettings,
    PostgresTenantBoundary,
)
from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository
from reconforge.infrastructure.postgres_scope_authority import (
    PostgresScopeAuthorityRepository,
    PrincipalScopeSnapshot,
)

ROOT = Path(__file__).resolve().parents[1]
CURRENT = "0104_pg_exception_review_api"
_APP_DSN = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_DSN") or os.environ.get(
    "RECONFORGE_TEST_POSTGRES_DSN"
)
pytestmark = pytest.mark.filterwarnings("error::DeprecationWarning")


def _record(*, exception_id: str = "EXQ-1", version: int = 1, status: str = "Open") -> dict[str, object]:
    return {
        "tenant_id": "tenant-a",
        "id": exception_id,
        "workspace_id": "workspace-a",
        "organization_id": "organization-a",
        "legal_entity_id": "entity-a",
        "source_type": "control",
        "source_id": "source-1",
        "period_name": "2026-10",
        "entity_code": "ENTITY-A",
        "account_code": "1010",
        "control_code": "CONTROL-1",
        "risk_rating": "high",
        "owner": "",
        "status": status,
        "escalation_level": "",
        "sla_target_date": None,
        "description": "Synthetic exception",
        "created_by": "maker-user",
        "last_actor": "maker",
        "created_at": "2026-10-04T00:00:00Z",
        "updated_at": "2026-10-04T00:00:00Z",
        "row_version": version,
        "history": [
            {
                "id": "EXH-1",
                "exception_id": exception_id,
                "action": "exception_saved",
                "from_status": "",
                "to_status": status,
                "from_owner": "",
                "to_owner": "",
                "actor_id": "",
                "actor_label": "maker",
                "reason": "",
                "occurred_at": "2026-10-04T00:00:00Z",
                "internal_note": "must not leave the repository boundary",
            }
        ],
        "internal_note": "must not leave the repository boundary",
    }


def test_server_exception_review_http_contract_is_scoped_and_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise the HTTP contract without making a database network call."""

    import reconforge.api.app as app_module
    import reconforge.api.dependencies as dependencies
    import reconforge.api.routes.exceptions as routes

    user = LocalUser(id="reviewer-user", username="reviewer", display_name="Reviewer")
    principal_scope = PrincipalScopeSnapshot(
        workspace_ids=frozenset({"workspace-a"}),
        organization_ids=frozenset({"organization-a"}),
        legal_entity_ids=frozenset({"entity-a"}),
    )

    def authenticate(_request: Any, credential: str) -> AuthenticatedServerRequest | None:
        if credential != "server-token":
            return None
        return AuthenticatedServerRequest(
            user=user,
            permissions=frozenset({"exceptions.read", "exceptions.manage"}),
            principal_type="user",
            tenant_id="tenant-a",
            scope_authority=principal_scope,
        )

    calls: list[tuple[str, ExceptionReviewScope, object]] = []

    class _Service:
        def list(self, scope: ExceptionReviewScope, query: object) -> list[dict[str, object]]:
            calls.append(("list", scope, query))
            return [_record()]

        def get(self, scope: ExceptionReviewScope, exception_id: str) -> dict[str, object]:
            calls.append(("get", scope, exception_id))
            return _record(exception_id=exception_id)

        def assign(self, scope: ExceptionReviewScope, command: object) -> dict[str, object]:
            calls.append(("assign", scope, command))
            return _record(version=2)

        def transition(self, scope: ExceptionReviewScope, command: object) -> dict[str, object]:
            calls.append(("transition", scope, command))
            return _record(version=3, status="In Review")

    service = _Service()

    monkeypatch.setattr(app_module, "authenticate_server_request", authenticate)
    monkeypatch.setattr(dependencies, "authenticate_server_request", authenticate)
    monkeypatch.setattr(dependencies, "server_audit_administration_enabled", lambda _request: False)
    monkeypatch.setattr(
        routes,
        "execute_postgres_exception_review",
        lambda _request, operation: operation(
            service,
            ExceptionReviewScope(
                tenant_id="tenant-a",
                workspace_id="workspace-a",
                organization_id="organization-a",
                legal_entity_id="entity-a",
            ),
        ),
    )
    app = create_api_app(
        tmp_path / "unused.db",
        tenant_db_root=tmp_path / "tenants",
        postgres_dsn="postgresql://unreachable.invalid/reconforge",
        postgres_require_tls=False,
    )
    headers = {
        "Authorization": "Bearer server-token",
        "X-ReconForge-Tenant": "tenant-a",
        "X-ReconForge-Workspace": "workspace-a",
        "X-ReconForge-Organization": "organization-a",
        "X-ReconForge-Legal-Entity": "entity-a",
    }

    with TestClient(app) as client:
        listed = client.get("/api/v1/exceptions", headers=headers, params={"status": "Open"})
        assert listed.status_code == 200, listed.text
        assert listed.json()["exceptions"][0]["id"] == "EXQ-1"
        assert "created_by" not in listed.json()["exceptions"][0]
        assert "internal_note" not in listed.json()["exceptions"][0]

        detail = client.get("/api/v1/exceptions/EXQ-1", headers=headers)
        assert detail.status_code == 200, detail.text
        assert detail.json()["exception"]["history"][0]["actor_id"] == ""
        assert "internal_note" not in detail.json()["exception"]["history"][0]

        missing_version = client.post(
            "/api/v1/exceptions/EXQ-1/assign",
            headers=headers,
            json={"owner": "reviewer-user"},
        )
        assert missing_version.status_code == 400
        assert missing_version.json()["error"]["code"] == "exception_review_expected_version_required"

        assigned = client.post(
            "/api/v1/exceptions/EXQ-1/assign",
            headers=headers,
            json={"owner": "reviewer-user", "expected_version": 1},
        )
        assert assigned.status_code == 200, assigned.text
        assert assigned.json()["exception"]["row_version"] == 2

        transitioned = client.post(
            "/api/v1/exceptions/EXQ-1/status",
            headers=headers,
            json={"status": "In Review", "expected_version": 2},
        )
        assert transitioned.status_code == 200, transitioned.text
        assert transitioned.json()["exception"]["status"] == "In Review"

        denied = client.get(
            "/api/v1/exceptions",
            headers={**headers, "X-ReconForge-Workspace": "workspace-other"},
        )
        assert denied.status_code == 403
        assert denied.json()["error"]["code"] == "workspace_scope_denied"

    assert [name for name, _, _ in calls] == ["list", "get", "assign", "transition"]
    assert all(call_scope.workspace_id == "workspace-a" for _, call_scope, _ in calls)


def _migrate(dsn: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", CURRENT],
        cwd=ROOT,
        env={**os.environ, "RECONFORGE_POSTGRES_DSN": dsn},
        capture_output=True,
        text=True,
        timeout=120,
    )


@pytest.fixture
def _live_database() -> Iterator[tuple[str, str, str]]:
    """Create a database owned only by this acceptance test and remove it after use."""

    if not os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN") or not _APP_DSN:
        pytest.skip("requires owned PostgreSQL administrator and application DSNs")
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", app_user):
        pytest.skip("requires a safe non-privileged PostgreSQL application role")
    psycopg = pytest.importorskip("psycopg")
    from psycopg import sql

    database = "reconforge_exception_review_http_" + uuid4().hex[:12]
    control_dsn = psycopg.conninfo.make_conninfo(
        os.environ["RECONFORGE_TEST_POSTGRES_ADMIN_DSN"],
        dbname="postgres",
        connect_timeout=5,
    )
    admin_dsn = urlunsplit(
        urlsplit(os.environ["RECONFORGE_TEST_POSTGRES_ADMIN_DSN"])._replace(path="/" + database)
    )
    app_dsn = urlunsplit(urlsplit(_APP_DSN)._replace(path="/" + database))
    with psycopg.connect(control_dsn, autocommit=True) as control:
        control.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
    try:
        migration = _migrate(admin_dsn)
        assert migration.returncode == 0, migration.stderr
        yield admin_dsn, app_dsn, app_user
    finally:
        with psycopg.connect(control_dsn, autocommit=True) as control:
            control.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database)))


def _grant_application_privileges(connection: Any, app_user: str) -> None:
    from psycopg import sql

    role = sql.Identifier(app_user)
    connection.execute(sql.SQL("GRANT USAGE ON SCHEMA reconforge TO {}").format(role))
    connection.execute(
        sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA reconforge TO {}").format(role)
    )
    connection.execute(
        sql.SQL("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA reconforge TO {}").format(role)
    )


def _bootstrap_live_review_fixture(
    admin_dsn: str,
    app_dsn: str,
    app_user: str,
) -> tuple[PostgresConnectionFactory, str, dict[str, str]]:
    """Seed synthetic identities, hierarchy grants, and one governed exception."""

    tenant = "exception-http-" + uuid4().hex[:8]
    workspace = "workspace-exception-http"
    organization = "organization-exception-http"
    legal_entity = "entity-exception-http"
    maker_id = "maker-exception-http"
    reviewer_id = "reviewer-exception-http"
    exception_id = "exception-http-" + uuid4().hex[:12]
    admin_factory = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False))
    app_factory = PostgresConnectionFactory(PostgresSettings(dsn=app_dsn, require_tls=False))
    with admin_factory.connect() as administrator, administrator.transaction():
        _grant_application_privileges(administrator, app_user)
        administrator.execute("INSERT INTO reconforge.tenants(id,name) VALUES(%s,%s)", (tenant, tenant))
        administrator.execute(
            "INSERT INTO reconforge.domain_workspaces(tenant_id,id,name) VALUES(%s,%s,%s)",
            (tenant, workspace, "Exception HTTP workspace"),
        )
        administrator.execute(
            "INSERT INTO reconforge.currencies(tenant_id,code,name,minor_units) VALUES(%s,'USD','US Dollar',2)",
            (tenant,),
        )
        administrator.execute(
            """INSERT INTO reconforge.organizations
               (tenant_id,id,name,organization_code,base_currency,application_workspace_id)
               VALUES(%s,%s,%s,%s,'USD',%s)""",
            (tenant, organization, "Exception HTTP organization", "EXHTTP", workspace),
        )
        administrator.execute(
            """INSERT INTO reconforge.legal_entities
               (tenant_id,id,organization_id,entity_code,name,currency_code)
               VALUES(%s,%s,%s,%s,%s,'USD')""",
            (tenant, legal_entity, organization, "EXHTTP-LE", "Exception HTTP entity"),
        )
        identity = PostgresIdentityRepository(administrator)
        identity.create_role(tenant_id=tenant, role_name="exception-reviewer")
        for permission in ("exceptions.read", "exceptions.manage"):
            identity.create_permission(tenant_id=tenant, permission_name=permission)
            identity.grant_permission(
                tenant_id=tenant,
                role_name="exception-reviewer",
                permission_name=permission,
            )
        identity.create_user(
            tenant_id=tenant,
            user_id=maker_id,
            username="maker",
            password="Synthetic-password-123",
            role_name="exception-reviewer",
        )
        identity.create_user(
            tenant_id=tenant,
            user_id=reviewer_id,
            username="reviewer",
            password="Synthetic-password-123",
            role_name="exception-reviewer",
        )
        scopes = PostgresScopeAuthorityRepository(administrator)
        for principal_id in (maker_id, reviewer_id):
            for scope_type, scope_id in (
                ("workspace", workspace),
                ("organization", organization),
                ("legal_entity", legal_entity),
            ):
                scopes.grant(
                    tenant_id=tenant,
                    grant_id=f"grant-{principal_id}-{scope_type}",
                    principal_type="user",
                    principal_id=principal_id,
                    scope_type=scope_type,
                    scope_id=scope_id,
                    actor_id="security-admin",
                )
        administrator.execute(
            """INSERT INTO reconforge.exception_queue_records(
                tenant_id,id,workspace_id,organization_id,legal_entity_id,source_type,source_id,
                description,created_by,last_actor)
            VALUES(%s,%s,%s,%s,%s,'control','source-1',%s,%s,%s)""",
            (
                tenant,
                exception_id,
                workspace,
                organization,
                legal_entity,
                "Synthetic HTTP review exception",
                maker_id,
                "maker",
            ),
        )
        administrator.execute(
            """INSERT INTO reconforge.exception_queue_history(
                tenant_id,id,exception_id,action,from_status,to_status,from_owner,to_owner,actor_label)
            VALUES(%s,%s,%s,'exception_saved','','Open','','','maker')""",
            (tenant, "history-" + exception_id, exception_id),
        )
    return app_factory, tenant, {
        "workspace": workspace,
        "organization": organization,
        "legal_entity": legal_entity,
        "maker_id": maker_id,
        "reviewer_id": reviewer_id,
        "exception_id": exception_id,
    }


def _login(client: TestClient, tenant: str, username: str) -> str:
    response = client.post(
        "/api/v1/auth/login",
        headers={"X-ReconForge-Tenant": tenant},
        json={"username": username, "password": "Synthetic-password-123"},
    )
    assert response.status_code == 200, response.text
    return str(response.json()["access_token"])


@pytest.mark.skipif(
    not os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN") or not _APP_DSN,
    reason="requires owned live PostgreSQL administrator and application DSNs",
)
def test_live_server_exception_review_is_scoped_atomic_and_non_superuser(
    tmp_path: Path,
    _live_database: tuple[str, str, str],
) -> None:
    """Run the real authenticated HTTP boundary against an owned PostgreSQL database."""

    psycopg = pytest.importorskip("psycopg")
    admin_dsn, app_dsn, app_user = _live_database
    app_factory, tenant, ids = _bootstrap_live_review_fixture(admin_dsn, app_dsn, app_user)
    with app_factory.connect() as application_connection:
        role = application_connection.execute(
            "SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user"
        ).fetchone()
    assert role is not None
    assert not bool(role[0])
    assert not bool(role[1])

    headers = {
        "X-ReconForge-Tenant": tenant,
        "X-ReconForge-Workspace": ids["workspace"],
        "X-ReconForge-Organization": ids["organization"],
        "X-ReconForge-Legal-Entity": ids["legal_entity"],
    }
    root = tmp_path / "tenants"
    root.mkdir()
    app = create_api_app(
        tmp_path / "unused.db",
        tenant_db_root=root,
        postgres_dsn=app_dsn,
        postgres_require_tls=False,
    )
    with TestClient(app) as client:
        maker_token = _login(client, tenant, "maker")
        reviewer_token = _login(client, tenant, "reviewer")
        maker = {**headers, "Authorization": f"Bearer {maker_token}"}
        reviewer = {**headers, "Authorization": f"Bearer {reviewer_token}"}

        listed = client.get("/api/v1/exceptions", headers=reviewer)
        assert listed.status_code == 200, listed.text
        assert [item["id"] for item in listed.json()["exceptions"]] == [ids["exception_id"]]
        assert listed.json()["exceptions"][0]["row_version"] == 1

        assigned = client.post(
            f"/api/v1/exceptions/{ids['exception_id']}/assign",
            headers=maker,
            json={"owner": ids["reviewer_id"], "expected_version": 1},
        )
        assert assigned.status_code == 200, assigned.text
        assert assigned.json()["exception"]["row_version"] == 2

        submitted = client.post(
            f"/api/v1/exceptions/{ids['exception_id']}/status",
            headers=maker,
            json={"status": "In Review", "expected_version": 2},
        )
        assert submitted.status_code == 200, submitted.text
        assert submitted.json()["exception"]["row_version"] == 3

        stale = client.post(
            f"/api/v1/exceptions/{ids['exception_id']}/status",
            headers=reviewer,
            json={"status": "Resolved", "expected_version": 2},
        )
        assert stale.status_code == 409
        assert stale.json()["error"]["code"] == "exception_review_conflict"

        self_review = client.post(
            f"/api/v1/exceptions/{ids['exception_id']}/status",
            headers=maker,
            json={"status": "Resolved", "expected_version": 3},
        )
        assert self_review.status_code == 409
        assert self_review.json()["error"]["code"] == "exception_self_review_refused"

        resolved = client.post(
            f"/api/v1/exceptions/{ids['exception_id']}/status",
            headers=reviewer,
            json={"status": "Resolved", "expected_version": 3, "reason": "Evidence reconciled."},
        )
        assert resolved.status_code == 200, resolved.text
        assert resolved.json()["exception"]["row_version"] == 4
        assert resolved.json()["exception"]["status"] == "Resolved"

        closed = client.post(
            f"/api/v1/exceptions/{ids['exception_id']}/status",
            headers=reviewer,
            json={"status": "Closed", "expected_version": 4, "reason": "Reviewer sign-off."},
        )
        assert closed.status_code == 200, closed.text
        assert closed.json()["exception"]["row_version"] == 5
        assert closed.json()["exception"]["status"] == "Closed"

        detail = client.get(f"/api/v1/exceptions/{ids['exception_id']}", headers=reviewer)
        assert detail.status_code == 200, detail.text
        body = detail.json()["exception"]
        assert body["organization_id"] == ids["organization"]
        assert body["legal_entity_id"] == ids["legal_entity"]
        assert [event["action"] for event in body["history"]] == [
            "exception_saved",
            "exception_review_assigned",
            "exception_review_transition",
            "exception_review_transition",
            "exception_review_transition",
        ]
        assert body["history"][-2]["actor_id"] == ids["reviewer_id"]
        assert body["history"][-2]["reason"] == "Evidence reconciled."
        assert "created_by" not in body

        sibling = client.get(
            "/api/v1/exceptions",
            headers={**reviewer, "X-ReconForge-Workspace": "workspace-not-granted"},
        )
        assert sibling.status_code == 403
        assert sibling.json()["error"]["code"] == "workspace_scope_denied"

    with (
        PostgresTenantBoundary(app_factory).transaction(
            tenant,
            organization_id=ids["organization"],
            workspace_id=ids["workspace"],
            legal_entity_id=ids["legal_entity"],
        ) as application_connection,
        pytest.raises(psycopg.Error, match="append-only"),
        application_connection.transaction(),
    ):
        application_connection.execute(
            "UPDATE reconforge.exception_queue_history SET reason='tamper' "
            "WHERE tenant_id=%s AND exception_id=%s",
            (tenant, ids["exception_id"]),
        )

    with psycopg.connect(admin_dsn) as administrator:
        audit_events = administrator.execute(
            "SELECT action FROM reconforge.domain_audit_events WHERE tenant_id=%s "
            "AND object_type='exception' AND object_id=%s ORDER BY sequence",
            (tenant, ids["exception_id"]),
        ).fetchall()
        outbox_events = administrator.execute(
            "SELECT event_type FROM reconforge.outbox_events WHERE tenant_id=%s "
            "AND aggregate_type='exception' AND aggregate_id=%s ORDER BY created_at,event_id",
            (tenant, ids["exception_id"]),
        ).fetchall()
    assert [str(row[0]) for row in audit_events] == [
        "exception_review_assigned",
        "exception_review_transition",
        "exception_review_transition",
        "exception_review_transition",
    ]
    assert [str(row[0]) for row in outbox_events] == [
        "exception_review_assigned",
        "exception_review_transition",
        "exception_review_transition",
        "exception_review_transition",
    ]
