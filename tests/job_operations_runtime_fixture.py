"""Synthetic real-job seed composed by the integrated HTTPS browser runtime."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

from reconforge.application.jobs import DurableJobApplicationService, DurableJobWorkerService, JobSubmission
from reconforge.auth.service import LocalAuthService
from reconforge.infrastructure.sqlite_jobs import SQLiteDurableJobRepository


def seed_job_operations(connection: sqlite3.Connection, *, tenant_id: str = "local",
                        workspace_id: str = "default", organization_id: str = "ORG-GFO",
                        entity_id: str = "ENTITY-GFO", admin_username: str = "gfo-admin",
                        reader_username: str = "gfo-reader", password: str = "Synthetic-Gfo-2026-Only",
                        create_users: bool = True) -> dict[str, object]:
    """Requires an owned migrated database and existing canonical hierarchy.

    This seed uses actual submission/worker failure transitions. It never inserts
    arbitrary job projections or repairs retained event evidence.
    """
    auth = LocalAuthService(connection)
    if create_users:
        if auth.users.get_by_username(admin_username) is None:
            auth.init_admin(username=admin_username, password=password)
        if auth.users.get_by_username(reader_username) is None:
            auth.create_user(username=reader_username, password=password, role="auditor-readonly")
        connection.execute("INSERT OR IGNORE INTO role_permissions(role_id,permission_name) VALUES('ROLE-auditor-readonly','ops.read')")
        connection.commit()
    actor = auth.users.get_by_username(admin_username)
    if actor is None:
        raise ValueError("Synthetic job operator must exist before seeding jobs.")
    now = datetime.now(UTC).replace(microsecond=0)
    def timestamp(value: datetime) -> str:
        return value.isoformat().replace("+00:00", "Z")
    repository = SQLiteDurableJobRepository(connection)
    application = DurableJobApplicationService(repository)
    for identifier in ("GFO-job-failed", "GFO-job-queued"):
        application.submit(JobSubmission(job_id=identifier, idempotency_scope="gfo-browser-fixture",
                                         idempotency_key=identifier, tenant_id=tenant_id,
                                         workspace_id=workspace_id, organization_id=organization_id,
                                         entity_id=entity_id, input_digest="1" * 64,
                                         config_digest="2" * 64, worker_version="fixture-worker-v1",
                                         total_units=2, retry_ceiling=2, created_at=timestamp(now - timedelta(minutes=2))),
                           actor_id=actor.id)
    failed = repository.get(tenant_id=tenant_id, job_id="GFO-job-failed")
    if failed is not None and failed.status.value == "queued":
        worker = DurableJobWorkerService(repository)
        leased = worker.claim(tenant_id=tenant_id, workspace_id=workspace_id,
                              organization_id=organization_id, entity_id=entity_id, worker_id="gfo-fixture-worker",
                              occurred_at=timestamp(now - timedelta(minutes=1)), lease_expires_at=timestamp(now + timedelta(minutes=5)))
        if leased is None or leased.job.id != "GFO-job-failed":
            raise ValueError("Synthetic worker did not claim its expected failure fixture.")
        worker.fail(leased, occurred_at=timestamp(now), safe_error_code="SYNTHETIC_RECOVERABLE_FAILURE")
    return {"tenant_id": tenant_id, "workspace_id": workspace_id, "organization_id": organization_id,
            "entity_id": entity_id, "queued_job_id": "GFO-job-queued", "failed_job_id": "GFO-job-failed",
            "admin_username": admin_username, "reader_username": reader_username}
