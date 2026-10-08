"""Owned PG17 migration, operator concurrency, RLS and native restore gate."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import secrets
import subprocess  # nosec B404
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import psycopg

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from reconforge.application.job_operations import JobOperationsScope, JobOperationsService  # noqa: E402
from reconforge.application.jobs import (  # noqa: E402
    DurableJobApplicationService,
    DurableJobWorkerService,
    GovernedDurableJobApplicationService,
    JobAuthorizationError,
    JobSubmission,
)
from reconforge.auth.policy import PolicyEvaluationContext  # noqa: E402
from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository  # noqa: E402
from reconforge.infrastructure.postgres_jobs import PostgresDurableJobRepository, PostgresJobConflictError  # noqa: E402
from reconforge.infrastructure.postgres_scope_authority import PostgresScopeAuthorityRepository  # noqa: E402

IMAGE = "postgres:17.10-alpine@sha256:742f40ea20b9ff2ff31db5458d127452988a2164df9e17441e191f3b72252193"


def submission(identifier: str, *, tenant_id: str = "local", entity_id: str = "entity-a") -> JobSubmission:
    return JobSubmission(job_id=identifier, idempotency_scope="imports", idempotency_key=identifier,
                         tenant_id=tenant_id, workspace_id="workspace-a", entity_id=entity_id,
                         input_digest="1" * 64, config_digest="2" * 64, worker_version="worker-v1",
                         total_units=2, retry_ceiling=1, created_at="2026-08-02T10:00:00Z")


def verify_server_http(admin_dsn: str, app_dsn: str) -> None:
    from fastapi.testclient import TestClient

    from reconforge.api import create_api_app
    from reconforge.api.routes.durable_job_operations import router
    from reconforge.db import run_migrations

    password = "Synthetic-Http-" + secrets.token_hex(16)
    with psycopg.connect(admin_dsn) as admin:
        admin.execute("GRANT SELECT ON ALL TABLES IN SCHEMA reconforge TO job_operator_app")
        admin.execute("GRANT INSERT,UPDATE ON reconforge.identity_sessions,reconforge.identity_users,reconforge.identity_step_up_assertions,reconforge.domain_audit_events,reconforge.domain_audit_ledger_state TO job_operator_app")
        admin.execute("GRANT UPDATE ON reconforge.emergency_access_requests TO job_operator_app")
        admin.execute("GRANT INSERT ON reconforge.emergency_access_events TO job_operator_app")
        admin.execute("INSERT INTO reconforge.domain_workspaces(tenant_id,id,name) VALUES('local','workspace-a','Synthetic workspace')")
        admin.execute("INSERT INTO reconforge.currencies(tenant_id,code,name,minor_units) VALUES('local','USD','Synthetic',2)")
        admin.execute("INSERT INTO reconforge.organizations(tenant_id,id,name,organization_code,application_workspace_id) VALUES('local','organization-a','Synthetic organization','ORG-A','workspace-a')")
        admin.execute("INSERT INTO reconforge.legal_entities(tenant_id,id,organization_id,entity_code,name,currency_code) VALUES('local','entity-a','organization-a','ENTITY-A','Synthetic entity','USD')")
        identity = PostgresIdentityRepository(admin)
        identity.create_permission(tenant_id="local", permission_name="ops.read", description="Synthetic operational read")
        identity.grant_permission(tenant_id="local", role_name="admin", permission_name="ops.read")
        identity.create_user(tenant_id="local", user_id="http-operator", username="http-operator", password=password, role_name="admin")
        grants = PostgresScopeAuthorityRepository(admin)
        for kind, identifier in (("workspace", "workspace-a"), ("organization", "organization-a"), ("legal_entity", "entity-a")):
            grants.grant(tenant_id="local", grant_id="http-grant-" + identifier, principal_type="user", principal_id="http-operator",
                         scope_type=kind, scope_id=identifier, actor_id="http-operator")
    with psycopg.connect(app_dsn) as connection:
        lifecycle = DurableJobApplicationService(PostgresDurableJobRepository(connection))
        lifecycle.submit(replace(submission("job-http"), organization_id="organization-a"), actor_id="http-operator")
    with tempfile.TemporaryDirectory(prefix="reconforge-job-http-") as raw:
        directory = Path(raw)
        tenants = directory / "tenants"
        tenants.mkdir()
        run_migrations(tenants / "local.db")
        app = create_api_app(directory / "unused.db", tenant_db_root=tenants,
                             postgres_dsn=app_dsn, postgres_require_tls=False)
        if "/api/v1/ops/durable-jobs" not in app.openapi()["paths"]:
            app.include_router(router, prefix="/api/v1")
        with TestClient(app) as client:
            login = client.post("/api/v1/auth/login", headers={"X-ReconForge-Tenant": "local"},
                                json={"username": "http-operator", "password": password})
            assert login.status_code == 200, "Synthetic PostgreSQL identity login failed"
            headers = {"Authorization": "Bearer " + login.json()["access_token"], "X-ReconForge-Tenant": "local",
                       "X-ReconForge-Workspace": "workspace-a", "X-ReconForge-Organization": "organization-a",
                       "X-ReconForge-Legal-Entity": "entity-a"}
            page = client.get("/api/v1/ops/durable-jobs", headers=headers)
            assert page.status_code == 200 and [row["id"] for row in page.json()["records"]] == ["job-http"], f"Authenticated scoped job page failed: {page.status_code}, {page.json().get('error', {}).get('code', 'unexpected_records')}"
            denied = client.post("/api/v1/ops/durable-jobs/job-http/cancel", headers=headers, json={"expected_version": 1})
            assert denied.status_code == 403 and denied.json()["error"]["code"] == "step_up_required", "Missing server step-up was accepted"
            elevated = client.post("/api/v1/auth/step-up", headers=headers, json={"password": password})
            assert elevated.status_code == 200, "Synthetic server step-up failed"
            foreign = client.get("/api/v1/ops/durable-jobs/job-http", headers={**headers, "X-ReconForge-Workspace": "ungranted"})
            assert foreign.status_code == 403, "Ungrantable workspace was disclosed"
            changed = client.post("/api/v1/ops/durable-jobs/job-http/cancel", headers=headers, json={"expected_version": 1})
            assert changed.status_code == 200 and changed.json()["job"]["status"] == "cancelled", "Authenticated job cancellation failed"
            with psycopg.connect(admin_dsn) as admin:
                admin.execute("UPDATE reconforge.principal_scope_grants SET revoked_by='http-operator',revoked_at=now(),revocation_reason='Synthetic current-grant refusal' WHERE tenant_id='local' AND id='http-grant-entity-a'")
            revoked = client.get("/api/v1/ops/durable-jobs/job-http", headers=headers)
            assert revoked.status_code == 403, "Revoked current entity authority still disclosed a job"


def run_gate() -> dict[str, object]:
    name = "reconforge-job-operations-" + uuid4().hex[:12]
    admin_password, app_password = "rf" + secrets.token_hex(24), "rf" + secrets.token_hex(24)
    def run(argv: list[str], *, environment: dict[str, str] | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(argv, cwd=ROOT, env=environment, capture_output=True, text=True, timeout=180)  # nosec B603
        if check and result.returncode:
            diagnostic = (result.stdout + result.stderr).replace(admin_password, "[redacted]").replace(app_password, "[redacted]")
            raise RuntimeError(diagnostic)
        return result
    environment = os.environ.copy()
    # Bind administrative subprocess imports to this checkout even when the
    # supplied Python runtime has an editable installation of another checkout.
    environment["PYTHONPATH"] = str(ROOT)
    cleanup = False
    report: dict[str, object] = {}
    started = time.monotonic()
    try:
        run(["docker", "run", "--rm", "-d", "--name", name, "-e", f"POSTGRES_PASSWORD={admin_password}", "-p", "127.0.0.1::5432", IMAGE])
        for _ in range(120):
            if run(["docker", "exec", name, "pg_isready", "-U", "postgres"], check=False).returncode == 0:
                break
            time.sleep(.25)
        else:
            raise RuntimeError("Owned PostgreSQL readiness timeout")
        port = run(["docker", "port", name, "5432/tcp"]).stdout.strip().rsplit(":", 1)[-1]
        admin_dsn = f"postgresql://postgres:{admin_password}@127.0.0.1:{port}/postgres?connect_timeout=10"
        app_dsn = f"postgresql://job_operator_app:{app_password}@127.0.0.1:{port}/postgres?connect_timeout=10"
        environment["RECONFORGE_POSTGRES_DSN"] = f"postgresql+psycopg://postgres:{admin_password}@127.0.0.1:{port}/postgres?connect_timeout=10"
        print("Owned job operations PostgreSQL: upgrade", flush=True)
        run([sys.executable, "-m", "alembic", "upgrade", "head"], environment=environment)
        print("Owned job operations PostgreSQL: identity seeds and bounded projection", flush=True)
        with psycopg.connect(admin_dsn, autocommit=True) as admin:
            captured_head = admin.execute("SELECT version_num FROM alembic_version").fetchone()[0]
            postgres_version = admin.execute("SHOW server_version").fetchone()[0]
            admin.execute(f"CREATE ROLE job_operator_app LOGIN PASSWORD '{app_password}'")
            admin.execute("GRANT USAGE ON SCHEMA reconforge TO job_operator_app")
            admin.execute("GRANT SELECT,INSERT,UPDATE ON reconforge.durable_jobs,reconforge.durable_job_transitions,reconforge.durable_job_leases,reconforge.durable_job_lease_events,reconforge.durable_job_partition_effects TO job_operator_app")
            admin.execute("GRANT DELETE ON reconforge.durable_job_leases TO job_operator_app")
            for tenant in ("local", "sibling"):
                admin.execute("INSERT INTO reconforge.tenants(id,name) VALUES(%s,%s)", (tenant, tenant))
            admin.execute("INSERT INTO reconforge.identity_roles(tenant_id,id,name,description) VALUES('local','admin-role','admin','Synthetic operator')")
            assert admin.execute("SELECT COUNT(*) FROM reconforge.identity_role_permissions WHERE tenant_id='local' AND role_id='admin-role' AND permission_name='jobs.manage'").fetchone()[0] == 1
            assert admin.execute("SELECT COUNT(*) FROM reconforge.identity_permissions WHERE name='jobs.manage'").fetchone()[0] == 2
        ctx = PolicyEvaluationContext(user_id="operator", username="operator", user_permissions={"ops.read", "jobs.manage"},
                                      tenant_id="local", workspace_id="workspace-a", entity_id="entity-a",
                                      authorized_tenant_ids=frozenset({"local"}), authorized_workspace_ids=frozenset({"workspace-a"}),
                                      authorized_entity_ids=frozenset({"entity-a"}))
        with psycopg.connect(app_dsn) as connection:
            repository = PostgresDurableJobRepository(connection)
            lifecycle = DurableJobApplicationService(repository)
            for identifier in ("job-a", "job-b", "job-c"):
                lifecycle.submit(submission(identifier), actor_id="operator")
            lifecycle.submit(submission("job-foreign", entity_id="entity-other"), actor_id="operator")
            lifecycle.submit(submission("job-sibling", tenant_id="sibling"), actor_id="operator")
            scope = JobOperationsScope("local", "workspace-a", "entity-a")
            reads = JobOperationsService(repository)
            first = reads.page(scope, ctx, limit=1)
            assert first["next_after_id"] == "job-a"
            last = reads.page(scope, ctx, after_id="job-a", limit=2)
            assert [record["id"] for record in last["records"]] == ["job-b", "job-c"]
            assert last["next_after_id"] == ""
            governed = GovernedDurableJobApplicationService(lifecycle)
            try:
                governed.cancel(tenant_id="local", workspace_id="workspace-a", entity_id="entity-other", job_id="job-a", actor_id="operator", occurred_at="2026-08-02T10:01:00Z", required_permission="jobs.manage", policy_context=replace(ctx, entity_id="entity-other", authorized_entity_ids=frozenset({"entity-other"})))
            except JobAuthorizationError:
                pass
            else:
                raise AssertionError("Persisted hierarchy confusion was allowed")
            with connection.transaction():
                connection.execute("SELECT set_config('app.tenant_id','local',true),set_config('app.workspace_id','workspace-a',true),set_config('app.entity_id','entity-a',true)")
                assert connection.execute("SELECT COUNT(*) FROM reconforge.durable_jobs WHERE tenant_id='sibling'").fetchone()[0] == 0
                assert connection.execute("SELECT COUNT(*) FROM reconforge.durable_jobs WHERE entity_id='entity-other'").fetchone()[0] == 0
        def cancel() -> int:
            with psycopg.connect(app_dsn) as connection:
                lifecycle = DurableJobApplicationService(PostgresDurableJobRepository(connection))
                try:
                    return lifecycle.cancel(tenant_id="local", job_id="job-a", actor_id="operator", occurred_at="2026-08-02T10:01:00Z", expected_version=1).version
                except PostgresJobConflictError:
                    return 0
        with ThreadPoolExecutor(max_workers=6) as pool:
            outcomes = list(pool.map(lambda _: cancel(), range(6)))
        assert 2 in outcomes and set(outcomes) <= {0, 2}
        print("Owned job operations PostgreSQL: lease fencing and replay", flush=True)
        with psycopg.connect(app_dsn) as connection:
            repository = PostgresDurableJobRepository(connection)
            lifecycle = DurableJobApplicationService(repository)
            assert len(repository.list_transitions(tenant_id="local", job_id="job-a")) == 2
            assert cancel() == 2
            worker = DurableJobWorkerService(repository)
            leased = worker.claim(tenant_id="local", workspace_id="workspace-a", entity_id="entity-a", worker_id="worker-a", occurred_at="2026-08-02T10:02:00Z", lease_expires_at="2026-08-02T10:10:00Z")
            assert leased is not None and leased.job.id == "job-b"
            try:
                lifecycle.cancel(tenant_id="local", job_id="job-b", actor_id="operator", occurred_at="2026-08-02T10:03:00Z", expected_version=leased.job.version)
            except PostgresJobConflictError:
                pass
            else:
                raise AssertionError("Active lease cancellation was allowed")
            failed = worker.fail(leased, occurred_at="2026-08-02T10:04:00Z", safe_error_code="SYNTHETIC_FAILURE")
            changed = lifecycle.requeue(tenant_id="local", job_id="job-b", actor_id="operator", occurred_at="2026-08-02T10:05:00Z", expected_version=failed.version)
            assert lifecycle.requeue(tenant_id="local", job_id="job-b", actor_id="operator", occurred_at="2026-08-02T10:06:00Z", expected_version=failed.version) == changed
        print("Owned job operations PostgreSQL: authenticated HTTP and current authority", flush=True)
        verify_server_http(admin_dsn, app_dsn)
        # Test this revision's guard in isolation from later additive revisions.
        # A moving head may have per-revision transactions and its own guards.
        if captured_head != "0107_pg_job_operations":
            run([sys.executable, "-m", "alembic", "downgrade", "0107_pg_job_operations"], environment=environment)
        with psycopg.connect(admin_dsn, autocommit=True) as admin:
            retained = admin.execute("SELECT id,version,status FROM reconforge.durable_jobs ORDER BY tenant_id,id").fetchall()
            admin.execute("INSERT INTO reconforge.identity_roles(tenant_id,id,name,description) VALUES('local','custom-role','custom-operator','Synthetic')")
            admin.execute("INSERT INTO reconforge.identity_role_permissions VALUES('local','custom-role','jobs.manage')")
        refused = run([sys.executable, "-m", "alembic", "downgrade", "0106_pg_ap_link_reversal"], environment=environment, check=False)
        assert refused.returncode != 0 and "refuses to discard nondefault permission grants" in refused.stderr
        with psycopg.connect(admin_dsn, autocommit=True) as admin:
            assert admin.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0107_pg_job_operations"
            admin.execute("DELETE FROM reconforge.identity_role_permissions WHERE tenant_id='local' AND role_id='custom-role'")
        run([sys.executable, "-m", "alembic", "downgrade", "0106_pg_ap_link_reversal"], environment=environment)
        with psycopg.connect(admin_dsn, autocommit=True) as admin:
            assert admin.execute("SELECT id,version,status FROM reconforge.durable_jobs ORDER BY tenant_id,id").fetchall() == retained
            assert admin.execute("SELECT COUNT(*) FROM reconforge.identity_permissions WHERE name='jobs.manage'").fetchone()[0] == 0
        run([sys.executable, "-m", "alembic", "upgrade", "head"], environment=environment)
        print("Owned job operations PostgreSQL: native dump and restore", flush=True)
        run(["docker", "exec", name, "pg_dump", "-U", "postgres", "-d", "postgres", "-Fc", "-f", "/tmp/jobs.dump"])
        run(["docker", "exec", name, "createdb", "-U", "postgres", "job_operations_restore"])
        run(["docker", "exec", name, "pg_restore", "--exit-on-error", "--no-owner", "-U", "postgres", "-d", "job_operations_restore", "/tmp/jobs.dump"])
        with psycopg.connect(admin_dsn.replace("/postgres?", "/job_operations_restore?"), autocommit=True) as restored:
            assert restored.execute("SELECT version_num FROM alembic_version").fetchone()[0] == captured_head
            assert restored.execute("SELECT id,version,status FROM reconforge.durable_jobs ORDER BY tenant_id,id").fetchall() == retained
            assert restored.execute("SELECT COUNT(*) FROM reconforge.durable_job_transitions WHERE tenant_id='local' AND job_id='job-a'").fetchone()[0] == 2
            assert restored.execute("SELECT COUNT(*) FROM pg_trigger WHERE tgname IN('job_operations_permission_tenant_seed','job_operations_permission_role_seed')").fetchone()[0] == 2
            assert restored.execute("SELECT COUNT(*) FROM pg_indexes WHERE indexname IN('durable_jobs_operator_lane_id','durable_jobs_operator_lane_status_id')").fetchone()[0] == 2
            assert restored.execute("SELECT COUNT(*) FROM pg_roles WHERE rolname='job_operator_app' AND (rolsuper OR rolbypassrls)").fetchone()[0] == 0
        files = ("reconforge/application/jobs.py", "reconforge/application/job_operations.py",
                 "reconforge/infrastructure/postgres_jobs.py", "alembic/versions/0107_postgres_job_operations.py",
                 ".github/scripts/verify_postgres_job_operations.py")
        report.update(status="passed", image=IMAGE, migration_head=captured_head, postgres_version=postgres_version,
                      python_version=platform.python_version(), source_commit=run(["git", "rev-parse", "HEAD"]).stdout.strip(),
                      source_files_sha256={path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in files},
                      checks=["future_tenant_and_admin_permission_seeds", "bounded_keyset_and_null_organization", "persisted_scope_refusal", "tenant_entity_rls", "six_concurrent_cancellations_one_transition", "same_actor_version_replay", "active_lease_fencing", "requeue_replay", "authenticated_nonowner_http", "http_human_stepup_required", "http_revoked_current_entity_scope_refused", "custom_grant_downgrade_refusal", "job_retaining_downgrade_upgrade", "native_dump_restore_jobs_transitions_indexes_triggers"],
                      concurrency_workers=6, skips=0, wall_seconds=round(time.monotonic() - started, 3))
        return report
    finally:
        cleanup = run(["docker", "rm", "-f", name], check=False).returncode == 0
        report["owned_container_removed"] = cleanup
        if not cleanup:
            raise RuntimeError("Owned PostgreSQL job operations container cleanup failed")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run_gate()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
