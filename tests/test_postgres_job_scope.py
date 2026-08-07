from __future__ import annotations

import os
import re
from uuid import uuid4

import pytest

from reconforge.application.jobs import DurableJobApplicationService, JobSubmission
from reconforge.infrastructure.postgres import PostgresConnectionFactory, PostgresSettings, PostgresTenantBoundary
from reconforge.infrastructure.postgres_job_scope import (
    POSTGRES_JOB_SCOPE_SCHEMA_SQL,
    install_postgres_job_scope_schema,
)
from reconforge.infrastructure.postgres_jobs import PostgresDurableJobRepository


class _Connection:
    def __init__(self) -> None:
        self.sql: list[str] = []

    def execute(self, sql: str) -> None:
        self.sql.append(sql)


def test_job_scope_policies_cover_parent_and_all_worker_evidence() -> None:
    normalized = " ".join(POSTGRES_JOB_SCOPE_SCHEMA_SQL.split())
    for table_name in (
        "durable_jobs",
        "durable_job_transitions",
        "durable_job_leases",
        "durable_job_lease_events",
        "durable_job_partition_effects",
    ):
        assert table_name in normalized
    assert "app.workspace_id" in normalized
    assert "app.organization_id" in normalized
    assert "app.entity_id" in normalized
    connection = _Connection()
    install_postgres_job_scope_schema(connection)
    assert connection.sql == [POSTGRES_JOB_SCOPE_SCHEMA_SQL]


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires live PostgreSQL")
def test_live_job_scope_hides_siblings_and_denies_child_evidence_write() -> None:
    psycopg = pytest.importorskip("psycopg")
    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", app_user):
        pytest.fail("RECONFORGE_TEST_POSTGRES_APP_USER is required and must be a safe role name")
    app_factory = PostgresConnectionFactory(PostgresSettings(dsn=dsn, require_tls=False))
    admin_factory = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False))
    token = uuid4().hex[:8]
    tenant = f"job_scope_{token}"
    job_a, job_b = f"job-a-{token}", f"job-b-{token}"
    admin = admin_factory.connect()
    app = app_factory.connect()
    try:
        with admin.transaction():
            admin.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
            admin.execute(
                f"GRANT SELECT, INSERT, UPDATE, DELETE ON reconforge.durable_jobs, "
                f"reconforge.durable_job_transitions, reconforge.durable_job_leases, "
                f"reconforge.durable_job_lease_events, reconforge.durable_job_partition_effects TO {app_user}"
            )
            admin.execute("INSERT INTO reconforge.tenants(id,name) VALUES(%s,%s)", (tenant, tenant))
        service = DurableJobApplicationService(PostgresDurableJobRepository(app))
        for job_id, workspace, entity, key in (
            (job_a, "workspace-a", "entity-a", "key-a"),
            (job_b, "workspace-b", "entity-b", "key-b"),
        ):
            service.submit(
                JobSubmission(
                    job_id=job_id,
                    idempotency_scope="isolation",
                    idempotency_key=key,
                    tenant_id=tenant,
                    workspace_id=workspace,
                    entity_id=entity,
                    input_digest="1" * 64,
                    config_digest="2" * 64,
                    worker_version="worker-v1",
                    total_units=1,
                    retry_ceiling=1,
                    created_at="2026-07-29T10:00:00Z",
                ),
                actor_id="synthetic-submitter",
            )
        with PostgresTenantBoundary(app_factory).transaction(tenant, workspace_id="workspace-a") as scoped:
            scoped.execute("SELECT set_config('app.entity_id', %s, true)", ("entity-a",))
            assert [row[0] for row in scoped.execute("SELECT id FROM reconforge.durable_jobs").fetchall()] == [job_a]
            assert [row[0] for row in scoped.execute(
                "SELECT job_id FROM reconforge.durable_job_transitions"
            ).fetchall()] == [job_a]
            with pytest.raises(psycopg.errors.InsufficientPrivilege), scoped.transaction():
                scoped.execute(
                    "INSERT INTO reconforge.durable_job_transitions"
                    "(tenant_id,job_id,job_version,from_status,to_status,actor_id,occurred_at,reason_code) "
                    "VALUES(%s,%s,2,'queued','cancelled','attacker','2026-07-29T10:01:00Z','CANCELLED')",
                    (tenant, job_b),
                )
    finally:
        app.close()
        with admin.transaction():
            for table_name, trigger_name in (
                ("durable_job_transitions", "durable_job_transitions_immutable"),
                ("durable_job_lease_events", "durable_job_lease_events_immutable"),
                ("durable_job_partition_effects", "durable_job_partition_effects_immutable"),
            ):
                admin.execute(f"ALTER TABLE reconforge.{table_name} DISABLE TRIGGER {trigger_name}")
            for table_name in (
                "durable_job_partition_effects", "durable_job_lease_events",
                "durable_job_leases", "durable_job_transitions", "durable_jobs",
            ):
                admin.execute(f"DELETE FROM reconforge.{table_name} WHERE tenant_id=%s", (tenant,))
        with admin.transaction():
            for table_name, trigger_name in (
                ("durable_job_transitions", "durable_job_transitions_immutable"),
                ("durable_job_lease_events", "durable_job_lease_events_immutable"),
                ("durable_job_partition_effects", "durable_job_partition_effects_immutable"),
            ):
                admin.execute(f"ALTER TABLE reconforge.{table_name} ENABLE TRIGGER {trigger_name}")
            admin.execute("DELETE FROM reconforge.tenants WHERE id=%s", (tenant,))
        admin.close()
