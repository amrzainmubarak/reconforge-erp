"""Restricted PostgreSQL checks for organization-aware worker claims."""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import pytest

from reconforge.auth.policy import PolicyEvaluationContext
from reconforge.deployment.worker_permissions import WorkerPermissionManifest
from reconforge.infrastructure.postgres import PostgresConnectionFactory, PostgresSettings, PostgresTenantBoundary
from reconforge.infrastructure.postgres_reconciliation import (
    PostgresReconciliationBusyError,
    PostgresReconciliationRepository,
)
from reconforge.workers.postgres_reconciliation import (
    LocalDeterministicMatcherAdapter,
    PostgresReconciliationPolicyDenied,
    PostgresReconciliationWorker,
    PostgresReconciliationWorkerError,
    PostgresReconciliationWorkerSettings,
)


@dataclass(frozen=True)
class _OwnedDatabase:
    admin_dsn: str = field(repr=False)
    app_dsn: str = field(repr=False)


@pytest.fixture
def owned_organization_database():
    """Create and drop only our randomly named database on a dedicated server."""
    admin_dsn = os.environ.get("RECONFORGE_OWNED_TEST_POSTGRES_ADMIN_DSN")
    app_dsn = os.environ.get("RECONFORGE_OWNED_TEST_POSTGRES_DSN")
    if not admin_dsn or not app_dsn:
        pytest.skip("requires dedicated owned PostgreSQL DSNs; review 2026-11-28")
    psycopg = pytest.importorskip("psycopg")
    from psycopg import sql

    admin_params = psycopg.conninfo.conninfo_to_dict(admin_dsn)
    app_params = psycopg.conninfo.conninfo_to_dict(app_dsn)
    if any(admin_params.get(key, "") != app_params.get(key, "") for key in ("host", "port")):
        pytest.fail("owned administrator and application DSNs must refer to the same test server")
    if not admin_params.get("host") or not app_params.get("user"):
        pytest.fail("owned test DSNs require an explicit host and restricted application role")
    if urlsplit(admin_dsn).scheme not in {"postgres", "postgresql"}:
        pytest.fail("owned administrator DSN must be a PostgreSQL URL")
    database = "reconforge_org_test_" + uuid4().hex
    with psycopg.connect(admin_dsn, autocommit=True) as control:
        control.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
    admin_db = psycopg.conninfo.make_conninfo(admin_dsn, dbname=database)
    app_db = psycopg.conninfo.make_conninfo(app_dsn, dbname=database)
    try:
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=Path(__file__).resolve().parents[1],
            env={**os.environ, "RECONFORGE_POSTGRES_DSN": urlunsplit(urlsplit(admin_dsn)._replace(path="/" + database))},
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=180, check=False,
        )
        assert result.returncode == 0, "migration failed on the owned synthetic database"
        with psycopg.connect(admin_db) as admin:
            role = sql.Identifier(app_params["user"])
            admin.execute(sql.SQL("GRANT USAGE ON SCHEMA reconforge TO {}").format(role))
            tables = ("audit_events", "outbox_events", "reconciliation_runs", "reconciliation_inputs",
                      "reconciliation_results", "reconciliation_exceptions", "reconciliation_execution_checkpoints")
            admin.execute(sql.SQL("GRANT SELECT,INSERT,UPDATE ON {} TO {}").format(
                sql.SQL(",").join(sql.Identifier("reconforge", table) for table in tables), role,
            ))
            admin.execute(sql.SQL("GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA reconforge TO {}").format(role))
            admin.execute("INSERT INTO reconforge.tenants(id,name) VALUES ('org-tenant','Synthetic')")
            admin.execute("INSERT INTO reconforge.domain_workspaces(tenant_id,id,name) VALUES ('org-tenant','workspace','Synthetic')")
            admin.execute("INSERT INTO reconforge.currencies(tenant_id,code,name,minor_units) VALUES ('org-tenant','USD','Dollar',2)")
            for organization in ("org_a", "org_b"):
                admin.execute("INSERT INTO reconforge.organizations(tenant_id,id,organization_code,name,base_currency,application_workspace_id) VALUES ('org-tenant',%s,%s,'Synthetic','USD','workspace')", (organization, organization))
                admin.execute("INSERT INTO reconforge.legal_entities(tenant_id,id,organization_id,entity_code,name,currency_code) VALUES ('org-tenant',%s,%s,%s,'Synthetic','USD')", ("entity_" + organization[-1], organization, "entity_" + organization[-1]))
            status = admin.execute(
                "SELECT relrowsecurity,relforcerowsecurity FROM pg_class "
                "WHERE oid='reconforge.reconciliation_runs'::regclass"
            ).fetchone()
            assert status == (True, True)
        with psycopg.connect(app_db) as connection:
            status = connection.execute(
                "SELECT rolsuper,rolbypassrls,rolcreatedb,rolcreaterole FROM pg_roles WHERE rolname=current_user"
            ).fetchone()
            assert status == (False, False, False, False)
        yield _OwnedDatabase(admin_db, app_db)
    finally:
        with psycopg.connect(admin_dsn, autocommit=True) as control:
            control.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database)))


def _context(tenant: str, workspace: str | None, organization: str | None, entity: str | None,
             *, grants: frozenset[str] = frozenset({"org_a"})) -> PolicyEvaluationContext:
    return PolicyEvaluationContext(
        user_id="worker", username="worker", principal_type="service_account",
        user_permissions=frozenset({"match.run", "match.discover"}), tenant_id=tenant,
        workspace_id=workspace, organization_id=organization, entity_id=entity,
        authorized_tenant_ids=frozenset({"org-tenant"}), authorized_workspace_ids=frozenset({"workspace"}),
        authorized_organization_ids=grants, authorized_entity_ids=frozenset({"entity_a", "entity_b"}),
    )


def _snapshot(admin_dsn: str):
    import psycopg

    with psycopg.connect(admin_dsn) as connection:
        runs = connection.execute(
            "SELECT * FROM reconforge.reconciliation_runs WHERE tenant_id='org-tenant' ORDER BY id"
        ).fetchall()
        counts = tuple(connection.execute(f"SELECT count(*) FROM reconforge.{name} WHERE tenant_id='org-tenant'").fetchone()[0]
                       for name in ("reconciliation_inputs", "reconciliation_results", "reconciliation_exceptions",
                                    "reconciliation_execution_checkpoints", "audit_events", "outbox_events"))
        return runs, counts


def test_real_worker_organization_denial_scope_changes_and_authorized_claim(owned_organization_database) -> None:
    admin_dsn, app_dsn = owned_organization_database.admin_dsn, owned_organization_database.app_dsn
    factory = PostgresConnectionFactory(PostgresSettings(dsn=app_dsn, require_tls=False))
    boundary = PostgresTenantBoundary(factory)
    for organization, entity, run in (("org_a", "entity_a", "run-a"), ("org_b", "entity_b", "run-b")):
        with boundary.transaction("org-tenant", workspace_id="workspace", organization_id=organization,
                                  legal_entity_id=entity) as connection:
            repository = PostgresReconciliationRepository(connection)
            repository.create_run(tenant_id="org-tenant", run_id=run, name="Synthetic", left_source="left",
                                  right_source="right", algorithm_version="synthetic-v1", rule={},
                                  input_hash="synthetic", actor_id="maker")
            for side in ("Left", "Right"):
                repository.register_input(tenant_id="org-tenant", run_id=run, side=side, source_id=side.lower(),
                                          record_hash="synthetic-" + side.lower(), amount="10.00", currency_code="USD",
                                          date_value="2026-10-28", reference_normalized="synthetic-reference")

    manifest = WorkerPermissionManifest(worker_id="worker", principal_id="worker", discovery_permission="match.discover",
                                        execution_permission="match.run", granted_permissions=("match.discover", "match.run"),
                                        scope="tenant:org-tenant")
    settings = PostgresReconciliationWorkerSettings(
        worker_id="worker", permission_manifest=manifest, discovery_policy_permission="match.discover",
        policy_context_hierarchy_supplier=_context,
    )
    worker = PostgresReconciliationWorker(factory, tenant_supplier=lambda: ["org-tenant"],
                                          matcher=LocalDeterministicMatcherAdapter(), settings=settings)
    before = _snapshot(admin_dsn)
    assert before[1][0] == 4

    with pytest.raises(PostgresReconciliationPolicyDenied, match="organization_scope_denied"):
        worker.process_run(tenant_id="org-tenant", run_id="run-b", workspace_id="workspace",
                           organization_id="org_b", entity_id="entity_b")
    assert _snapshot(admin_dsn) == before

    with pytest.raises(PostgresReconciliationWorkerError):
        worker.process_run(tenant_id="org-tenant", run_id="run-b", workspace_id="workspace",
                           organization_id="org_a", entity_id="entity_b")
    assert _snapshot(admin_dsn) == before

    with pytest.raises(PostgresReconciliationBusyError):
        worker.process_run(tenant_id="org-tenant", run_id="run-b", workspace_id="workspace")
    assert _snapshot(admin_dsn) == before

    with pytest.raises(PostgresReconciliationWorkerError, match="requires an organization"):
        worker.process_run(tenant_id="org-tenant", run_id="run-b", workspace_id="workspace", entity_id="entity_b")
    assert _snapshot(admin_dsn) == before

    scoped_calls = 0

    def revoked(tenant: str, workspace: str | None, organization: str | None, entity: str | None):
        nonlocal scoped_calls
        if organization is not None:
            scoped_calls += 1
        return _context(tenant, workspace, organization, entity,
                        grants=frozenset({"org_a"}) if scoped_calls < 2 else frozenset())

    revoked_worker = PostgresReconciliationWorker(
        factory, tenant_supplier=lambda: ["org-tenant"], matcher=LocalDeterministicMatcherAdapter(),
        settings=PostgresReconciliationWorkerSettings(
            worker_id="worker", permission_manifest=manifest, discovery_policy_permission="match.discover",
            policy_context_hierarchy_supplier=revoked,
        ),
    )
    with pytest.raises(PostgresReconciliationPolicyDenied, match="organization_scope_denied"):
        revoked_worker.process_run(tenant_id="org-tenant", run_id="run-a", workspace_id="workspace",
                                   organization_id="org_a", entity_id="entity_a")
    assert scoped_calls == 2
    assert _snapshot(admin_dsn) == before

    result = worker.process_run(tenant_id="org-tenant", run_id="run-a", workspace_id="workspace",
                                organization_id="org_a", entity_id="entity_a")
    with boundary.transaction("org-tenant", workspace_id="workspace", organization_id="org_a",
                              legal_entity_id="entity_a") as connection:
        repository = PostgresReconciliationRepository(connection)
        final_run = repository.get_run(tenant_id="org-tenant", run_id="run-a")
        assert result.status == "Complete", final_run["execution_error"]
        assert final_run["execution_status"] == "Complete"
        assert len(repository.list_results(tenant_id="org-tenant", run_id="run-a")) == 1
