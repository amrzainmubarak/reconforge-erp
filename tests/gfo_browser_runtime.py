"""Real restricted PostgreSQL identity, jobs and receipt masters for HTTPS acceptance."""
from __future__ import annotations

import os
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import uvicorn

from reconforge.api import create_api_app
from reconforge.application.jobs import DurableJobApplicationService, DurableJobWorkerService, JobSubmission
from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository
from reconforge.infrastructure.postgres_jobs import PostgresDurableJobRepository
from reconforge.infrastructure.postgres_scope_authority import PostgresScopeAuthorityRepository
from tests.https_runtime import create_localhost_certificate
from tests.test_postgres_inventory_receipt_posting import ReceiptRuntime


def seed_browser_jobs(runtime: ReceiptRuntime) -> None:
    """Separate read-only and operator principals use actual persisted transitions."""
    with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant) as connection:
        identities = PostgresIdentityRepository(connection)
        authority = PostgresScopeAuthorityRepository(connection)
        for role, username, permissions in (
            ("gfo-job-reader", "gfo-reader", ("ops.read",)),
            ("gfo-job-operator", "gfo-admin", ("ops.read", "jobs.manage")),
        ):
            identities.create_role(tenant_id=runtime.tenant, role_name=role)
            for permission in permissions:
                identities.create_permission(tenant_id=runtime.tenant, permission_name=permission)
                identities.grant_permission(tenant_id=runtime.tenant, role_name=role, permission_name=permission)
            identities.create_user(tenant_id=runtime.tenant, user_id=username, username=username,
                                   password=runtime.password, role_name=role)
            for kind, identifier in (("workspace", "work"), ("organization", "org"), ("legal_entity", "entity")):
                authority.grant(tenant_id=runtime.tenant, grant_id=f"browser-{username}-{identifier}",
                                principal_type="user", principal_id=username, scope_type=kind,
                                scope_id=identifier, actor_id=username)
    now = datetime.now(UTC).replace(microsecond=0)
    def timestamp(value: datetime) -> str:
        return value.isoformat().replace("+00:00", "Z")
    with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant, workspace_id="work",
                                                              organization_id="org", legal_entity_id="entity") as connection:
        repository = PostgresDurableJobRepository(connection)
        application = DurableJobApplicationService(repository)
        for identifier in ("GFO-job-failed", "GFO-job-queued"):
            application.submit(JobSubmission(job_id=identifier, idempotency_scope="gfo-browser-fixture",
                idempotency_key=identifier, tenant_id=runtime.tenant, workspace_id="work", organization_id="org",
                entity_id="entity", input_digest="1" * 64, config_digest="2" * 64,
                worker_version="fixture-worker-v1", total_units=2, retry_ceiling=2,
                created_at=timestamp(now - timedelta(minutes=2))), actor_id="gfo-admin")
        worker = DurableJobWorkerService(repository)
        leased = worker.claim(tenant_id=runtime.tenant, workspace_id="work", organization_id="org", entity_id="entity",
                              worker_id="gfo-fixture-worker", occurred_at=timestamp(now - timedelta(minutes=1)),
                              lease_expires_at=timestamp(now + timedelta(minutes=5)))
        if leased is None or leased.job.id != "GFO-job-failed":
            raise ValueError("Worker must claim exactly the synthetic failure fixture.")
        worker.fail(leased, occurred_at=timestamp(now), safe_error_code="SYNTHETIC_RECOVERABLE_FAILURE")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="reconforge-gfo-https-") as raw:
        directory = Path(raw)
        certificate, key = create_localhost_certificate(directory)
        app = create_api_app(directory / "local.db", tenant_db_root=directory / "tenants",
                             postgres_dsn=os.environ["RECONFORGE_GFO_APP_DSN"], postgres_require_tls=False,
                             web_root=Path(os.environ["RECONFORGE_GFO_WEB_ROOT"]),
                             allowed_hosts=("localhost",), secure_transport=True)
        uvicorn.run(app, host="127.0.0.1", port=int(os.environ["RECONFORGE_GFO_HTTPS_PORT"]),
                    ssl_certfile=str(certificate), ssl_keyfile=str(key), log_level="warning")


if __name__ == "__main__":
    main()
