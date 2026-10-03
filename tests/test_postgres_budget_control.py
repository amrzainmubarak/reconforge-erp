"""PostgreSQL authority, recovery, race, and HTTP acceptance for budget control."""

from __future__ import annotations

import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from typing import Any, Literal

import pytest
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.auth.models import LocalUser
from reconforge.domain.budget_control import BudgetControlError, BudgetDefinition, BudgetScope, CommitmentAction
from reconforge.infrastructure.budget_control_verification import verify_postgres_budget_storage
from reconforge.infrastructure.postgres_budget_control import PostgresBudgetControlRepository
from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository
from reconforge.infrastructure.postgres_scope_authority import PostgresScopeAuthorityRepository
from reconforge.platform.common import ServerPrincipal, server_principal_context

pytest_plugins = ("tests.test_postgres_finance_scope",)

TENANT = "finance_scope"
SCOPE = BudgetScope("shared", "org_a", "entity_a1")
PASSWORD = "Synthetic-Amr-Budget-Postgres-2026!"
READ = "budget_control.read"
MANAGE = "budget_control.manage"
APPROVE = "budget_control.approve"


def _principal(user: LocalUser, permissions: frozenset[str]) -> ServerPrincipal:
    return ServerPrincipal(
        user=user,
        permissions=permissions,
        step_up_active=True,
        authorized_tenant_ids=frozenset({TENANT}),
        authorized_workspace_ids=frozenset({SCOPE.workspace_id}),
        authorized_organization_ids=frozenset({SCOPE.organization_id}),
        authorized_legal_entity_ids=frozenset({SCOPE.legal_entity_id}),
    )


@pytest.fixture
def budget_postgres(finance_database: Any) -> Iterator[dict[str, Any]]:
    """Use the registered Alembic budget schema in one fixture-owned database."""

    psycopg = pytest.importorskip("psycopg")
    app_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_DSN")
    if not app_dsn:
        pytest.skip("requires a nonowner PostgreSQL application DSN")
    app_user = str(psycopg.conninfo.conninfo_to_dict(app_dsn)["user"])
    with psycopg.connect(finance_database["admin"], autocommit=True) as administrator:
        current_revision = str(administrator.execute("SELECT version_num FROM alembic_version").fetchone()[0])
        revisions = {
            revision.revision
            for revision in ScriptDirectory.from_config(finance_database["config"]).walk_revisions(
                base="base", head=current_revision
            )
        }
        assert "0102_pg_budget_control" in revisions
        tables = tuple(
            administrator.execute(
                "SELECT c.relname,c.relrowsecurity,c.relforcerowsecurity "
                "FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname='reconforge' AND c.relname=ANY(%s) ORDER BY c.relname",
                (["budget_envelopes", "budget_commitment_events", "budget_commands"],),
            )
        )
        assert tables == (
            ("budget_commands", True, True),
            ("budget_commitment_events", True, True),
            ("budget_envelopes", True, True),
        )
        administrator.execute(
            psycopg.sql.SQL(
                "GRANT SELECT,INSERT,UPDATE,DELETE ON "
                "reconforge.budget_envelopes,reconforge.budget_commitment_events,reconforge.budget_commands TO {}"
            ).format(psycopg.sql.Identifier(app_user))
        )

    users: dict[str, LocalUser] = {}
    permissions = {
        "maker": frozenset({READ, MANAGE}),
        "checker": frozenset({READ, APPROVE}),
    }
    with finance_database["boundary"].transaction(TENANT) as connection:
        identities = PostgresIdentityRepository(connection)
        authority = PostgresScopeAuthorityRepository(connection)
        for permission in (READ, MANAGE, APPROVE):
            identities.create_permission(tenant_id=TENANT, permission_name=permission)
        for label, granted in permissions.items():
            role_name = f"budget-{label}"
            identities.create_role(tenant_id=TENANT, role_name=role_name)
            for permission in granted:
                identities.grant_permission(tenant_id=TENANT, role_name=role_name, permission_name=permission)
            user = identities.create_user(
                tenant_id=TENANT,
                user_id=f"budget-{label}",
                username=label,
                password=PASSWORD,
                role_name=role_name,
            )
            users[label] = user
            scope_grants: tuple[tuple[Literal["workspace", "organization", "legal_entity"], str], ...] = (
                ("workspace", SCOPE.workspace_id),
                ("organization", SCOPE.organization_id),
                ("legal_entity", SCOPE.legal_entity_id),
            )
            for scope_type, scope_id in scope_grants:
                authority.grant(
                    tenant_id=TENANT,
                    grant_id=f"budget-{label}-{scope_type}",
                    principal_type="user",
                    principal_id=user.id,
                    scope_type=scope_type,
                    scope_id=scope_id,
                    actor_id=user.id,
                )
    yield {**finance_database, "users": users, "permissions": permissions}


def _approved_budget(database: dict[str, Any], *, code: str = "OPS") -> dict[str, Any]:
    users = database["users"]
    permissions = database["permissions"]
    with database["boundary"].transaction(
        TENANT,
        workspace_id=SCOPE.workspace_id,
        organization_id=SCOPE.organization_id,
        legal_entity_id=SCOPE.legal_entity_id,
    ) as connection:
        repository = PostgresBudgetControlRepository(connection, TENANT)
        with server_principal_context(_principal(users["maker"], permissions["maker"])):
            budget = repository.create(
                SCOPE,
                BudgetDefinition(code, "Synthetic PostgreSQL appropriation", "period", "EGP", 100),
                command_id=f"{code}-create",
            )
            budget = repository.transition(
                SCOPE,
                budget["id"],
                action="submit",
                expected_version=1,
                reason="Synthetic submission",
                command_id=f"{code}-submit",
            )
        with server_principal_context(_principal(users["checker"], permissions["checker"])):
            return repository.transition(
                SCOPE,
                budget["id"],
                action="approve",
                expected_version=2,
                reason="Synthetic independent approval",
                command_id=f"{code}-approve",
            )


def test_postgres_budget_rechecks_authority_replays_evidence_and_serializes_capacity(budget_postgres: dict[str, Any]) -> None:
    psycopg = pytest.importorskip("psycopg")
    database = budget_postgres
    users = database["users"]
    permissions = database["permissions"]
    budget = _approved_budget(database)
    ready = Barrier(2)

    def reserve(command_id: str) -> tuple[bool, dict[str, Any] | None]:
        with database["boundary"].transaction(
            TENANT,
            workspace_id=SCOPE.workspace_id,
            organization_id=SCOPE.organization_id,
            legal_entity_id=SCOPE.legal_entity_id,
        ) as connection:
            repository = PostgresBudgetControlRepository(connection, TENANT)
            with server_principal_context(_principal(users["maker"], permissions["maker"])):
                ready.wait(timeout=10)
                try:
                    return True, repository.record(
                        SCOPE,
                        budget["id"],
                        CommitmentAction("Reserve", 70, "2026-07-15", command_id, "Synthetic concurrent commitment"),
                        expected_version=3,
                        command_id=command_id,
                    )
                except BudgetControlError:
                    return False, None

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = tuple(pool.map(reserve, ("race-a", "race-b")))
    successful = [result for accepted, result in outcomes if accepted]
    assert len(successful) == 1
    accepted = successful[0]
    assert accepted is not None and accepted["reserved_minor"] == "70"

    with database["boundary"].transaction(
        TENANT,
        workspace_id=SCOPE.workspace_id,
        organization_id=SCOPE.organization_id,
        legal_entity_id=SCOPE.legal_entity_id,
    ) as connection:
        repository = PostgresBudgetControlRepository(connection, TENANT)
        with server_principal_context(_principal(users["maker"], permissions["maker"])):
            winning_command_id = "race-a" if outcomes[0][0] else "race-b"
            replay = repository.record(
                SCOPE,
                budget["id"],
                CommitmentAction("Reserve", 70, "2026-07-15", winning_command_id, "Synthetic concurrent commitment"),
                expected_version=3,
                command_id=winning_command_id,
            )
            assert replay == accepted
        verify_postgres_budget_storage(connection, TENANT)
        retained = connection.execute(
            "SELECT reserved_minor,row_version FROM reconforge.budget_envelopes WHERE tenant_id=%s AND id=%s",
            (TENANT, budget["id"]),
        ).fetchone()
        assert retained is not None and (retained["reserved_minor"], retained["row_version"]) == (70, 4)
        with pytest.raises(psycopg.Error), connection.transaction():
            connection.execute(
                "UPDATE reconforge.budget_envelopes SET reserved_minor=0,row_version=row_version+1 "
                "WHERE tenant_id=%s AND id=%s",
                (TENANT, budget["id"]),
            )

    with database["boundary"].transaction(TENANT) as connection:
        connection.execute(
            "UPDATE reconforge.identity_user_roles SET active=FALSE,lifecycle_version=lifecycle_version+1,"
            "revoked_at=now(),revoked_by=%s,revocation_reason_code='security_response' "
            "WHERE tenant_id=%s AND user_id=%s AND active",
            (users["checker"].id, TENANT, users["maker"].id),
        )
    with database["boundary"].transaction(
        TENANT,
        workspace_id=SCOPE.workspace_id,
        organization_id=SCOPE.organization_id,
        legal_entity_id=SCOPE.legal_entity_id,
    ) as connection:
        repository = PostgresBudgetControlRepository(connection, TENANT)
        with server_principal_context(_principal(users["maker"], permissions["maker"])), pytest.raises(
            BudgetControlError, match="persisted identity or authority"
        ):
            repository.record(
                SCOPE,
                budget["id"],
                CommitmentAction("Reserve", 70, "2026-07-15", "race-a", "Synthetic concurrent commitment"),
                expected_version=3,
                command_id="race-a",
            )


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "X-ReconForge-Tenant": TENANT,
        "X-ReconForge-Workspace": SCOPE.workspace_id,
        "X-ReconForge-Organization": SCOPE.organization_id,
        "X-ReconForge-Legal-Entity": SCOPE.legal_entity_id,
    }


def _payload(*, command_id: str, legal_entity_id: str = SCOPE.legal_entity_id) -> dict[str, Any]:
    return {
        "workspace_id": SCOPE.workspace_id,
        "organization_id": SCOPE.organization_id,
        "legal_entity_id": legal_entity_id,
        "budget_code": "HTTP",
        "name": "Synthetic authenticated HTTP appropriation",
        "period_id": "period",
        "currency_code": "EGP",
        "limit_minor": "10000",
        "command_id": command_id,
    }


def test_postgres_budget_api_requires_step_up_binds_scope_and_rechecks_live_authority(
    budget_postgres: dict[str, Any], tmp_path: Path
) -> None:
    psycopg = pytest.importorskip("psycopg")
    database = budget_postgres
    app_parameters = psycopg.conninfo.conninfo_to_dict(os.environ["RECONFORGE_TEST_POSTGRES_DSN"])
    app_parameters["dbname"] = psycopg.conninfo.conninfo_to_dict(database["admin"])["dbname"]
    tenant_root = tmp_path / "tenants"
    tenant_root.mkdir()
    app = create_api_app(
        tmp_path / "unused-local.db",
        tenant_db_root=tenant_root,
        postgres_dsn=psycopg.conninfo.make_conninfo(**app_parameters),
        postgres_require_tls=False,
        postgres_pool_size=4,
    )
    with TestClient(app) as client:
        login_headers = {"X-ReconForge-Tenant": TENANT}
        tokens: dict[str, str] = {}
        for username in ("maker", "checker"):
            login = client.post("/api/v1/auth/login", headers=login_headers, json={"username": username, "password": PASSWORD})
            assert login.status_code == 200, login.text
            tokens[username] = str(login.json()["access_token"])
        maker = _headers(tokens["maker"])
        checker = _headers(tokens["checker"])
        no_step_up = client.post("/api/v1/budget-control/envelopes", headers=maker, json=_payload(command_id="http-create"))
        assert no_step_up.status_code == 403
        for headers in (maker, checker):
            step_up = client.post("/api/v1/auth/step-up", headers=headers, json={"password": PASSWORD})
            assert step_up.status_code == 200, step_up.text
        scope_mismatch = client.post(
            "/api/v1/budget-control/envelopes",
            headers=maker,
            json=_payload(command_id="http-mismatch", legal_entity_id="entity_a2"),
        )
        assert scope_mismatch.status_code == 403
        created = client.post("/api/v1/budget-control/envelopes", headers=maker, json=_payload(command_id="http-create"))
        assert created.status_code == 200, created.text
        budget = created.json()
        scope = {"workspace_id": SCOPE.workspace_id, "organization_id": SCOPE.organization_id, "legal_entity_id": SCOPE.legal_entity_id}
        submitted = client.post(
            f"/api/v1/budget-control/envelopes/{budget['id']}/submit",
            headers=maker,
            json={**scope, "expected_version": 1, "reason": "Synthetic HTTP submission", "command_id": "http-submit"},
        )
        assert submitted.status_code == 200, submitted.text
        self_approval = client.post(
            f"/api/v1/budget-control/envelopes/{budget['id']}/approve",
            headers=maker,
            json={**scope, "expected_version": 2, "reason": "Synthetic self approval", "command_id": "http-self"},
        )
        assert self_approval.status_code == 403
        approved = client.post(
            f"/api/v1/budget-control/envelopes/{budget['id']}/approve",
            headers=checker,
            json={**scope, "expected_version": 2, "reason": "Synthetic independent approval", "command_id": "http-approve"},
        )
        assert approved.status_code == 200, approved.text

        with psycopg.connect(database["admin"], autocommit=True) as administrator:
            administrator.execute(
                "UPDATE reconforge.identity_user_roles SET active=FALSE,lifecycle_version=lifecycle_version+1,"
                "revoked_at=now(),revoked_by='budget-checker',revocation_reason_code='security_response' "
                "WHERE tenant_id=%s AND user_id='budget-maker' AND active",
                (TENANT,),
            )
        revoked = client.post(
            f"/api/v1/budget-control/envelopes/{budget['id']}/commitments",
            headers=maker,
            json={
                **scope,
                "expected_version": 3,
                "reason": "Synthetic revoked request",
                "command_id": "http-revoked-reserve",
                "operation": "Reserve",
                "amount_minor": "1",
                "operation_date": "2026-07-15",
                "source_reference": "PO/HTTP/1",
            },
        )
        assert revoked.status_code == 403
