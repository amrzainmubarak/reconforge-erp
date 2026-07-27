from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

from reconforge.application.jobs import (
    DurableJobApplicationService,
    DurableJobWorkerService,
    JobSubmission,
)
from reconforge.db import connect, run_migrations
from reconforge.domain.jobs import JobOutputManifest, JobPartitionEffect
from reconforge.infrastructure.postgres import (
    PostgresConnectionFactory,
    PostgresSettings,
    install_postgres_rls_schema,
)
from reconforge.infrastructure.postgres_jobs import (
    POSTGRES_DURABLE_JOB_SCHEMA_SQL,
    PostgresDurableJobRepository,
    PostgresJobConflictError,
    install_postgres_durable_job_schema,
)
from reconforge.infrastructure.sqlite_jobs import SQLiteDurableJobRepository


def _submission(tenant_id: str) -> JobSubmission:
    return JobSubmission(
        job_id="job-" + uuid4().hex[:16], idempotency_scope="imports", idempotency_key="same-key",
        tenant_id=tenant_id, workspace_id="workspace-a", entity_id="entity-a",
        input_digest="1" * 64, config_digest="2" * 64, worker_version="worker-v1",
        total_units=10, retry_ceiling=2, created_at="2026-07-27T09:00:00Z",
    )


def test_postgres_job_schema_has_rls_idempotency_and_version_guards() -> None:
    assert "FORCE ROW LEVEL SECURITY" in POSTGRES_DURABLE_JOB_SCHEMA_SQL
    assert "UNIQUE (tenant_id, idempotency_scope, idempotency_key)" in POSTGRES_DURABLE_JOB_SCHEMA_SQL
    assert "PRIMARY KEY (tenant_id, job_id, job_version)" in POSTGRES_DURABLE_JOB_SCHEMA_SQL
    assert "completed_units <= total_units" in POSTGRES_DURABLE_JOB_SCHEMA_SQL


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires live PostgreSQL")
def test_live_postgres_job_application_contract_and_rls(tmp_path: Path) -> None:
    psycopg = pytest.importorskip("psycopg")
    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if not app_user:
        pytest.skip("requires a non-privileged application role")
    factory = PostgresConnectionFactory(PostgresSettings(dsn=dsn, require_tls=False))
    admin_factory = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False))
    tenant_a = "jobs_live_a_" + uuid4().hex[:8]
    tenant_b = "jobs_live_b_" + uuid4().hex[:8]
    admin = admin_factory.connect()
    try:
        with admin.transaction():
            install_postgres_rls_schema(admin)
            install_postgres_durable_job_schema(admin)
            admin.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
            admin.execute(
                f"GRANT SELECT, INSERT, UPDATE ON reconforge.durable_jobs, "
                f"reconforge.durable_job_transitions, reconforge.durable_job_leases, "
                f"reconforge.durable_job_lease_events, "
                f"reconforge.durable_job_partition_effects TO {app_user}"
            )
            admin.execute(
                f"GRANT DELETE ON reconforge.durable_job_leases TO {app_user}"
            )
            for tenant in (tenant_a, tenant_b):
                admin.execute("INSERT INTO reconforge.tenants (id, name) VALUES (%s, %s)", (tenant, tenant))
        connection = factory.connect()
        try:
            repository = PostgresDurableJobRepository(connection)
            service = DurableJobApplicationService(repository)
            concurrent_submission = replace(
                _submission(tenant_a), idempotency_key="concurrent-key"
            )

            def submit_concurrently() -> tuple[str, bool]:
                concurrent_connection = factory.connect()
                try:
                    concurrent_service = DurableJobApplicationService(
                        PostgresDurableJobRepository(concurrent_connection)
                    )
                    job, created_now = concurrent_service.submit(
                        concurrent_submission, actor_id="concurrent-submitter"
                    )
                    return job.id, created_now
                finally:
                    concurrent_connection.close()

            with ThreadPoolExecutor(max_workers=2) as executor:
                concurrent_results = list(executor.map(lambda _: submit_concurrently(), range(2)))
            assert {job_id for job_id, _ in concurrent_results} == {concurrent_submission.job_id}
            assert sorted(created_now for _, created_now in concurrent_results) == [False, True]
            service.cancel(
                tenant_id=tenant_a, job_id=concurrent_submission.job_id,
                actor_id="operator", occurred_at="2026-07-27T09:00:30Z",
            )
            submission = _submission(tenant_a)
            created, is_new = service.submit(submission, actor_id="submitter")
            replayed, replay_is_new = service.submit(submission, actor_id="submitter")
            assert is_new is True and replay_is_new is False and replayed == created
            with pytest.raises(PostgresJobConflictError):
                service.submit(replace(submission, job_id="different-job", total_units=11), actor_id="submitter")
            assert repository.get(tenant_id=tenant_b, job_id=created.id) is None
            cancelled = service.cancel(
                tenant_id=tenant_a, job_id=created.id, actor_id="operator",
                occurred_at="2026-07-27T09:01:00Z",
            )
            assert cancelled.version == 2 and cancelled.status.value == "cancelled"
            stale_changed, stale_event = created.transition(
                cancelled.status, actor_id="operator", occurred_at="2026-07-27T09:01:00Z",
                reason_code="CANCELLED",
            )
            with pytest.raises(PostgresJobConflictError):
                repository.persist_transition(created, stale_changed, stale_event)

            workload, _ = service.submit(
                replace(_submission(tenant_a), idempotency_key="partition-workload"),
                actor_id="submitter",
            )
            worker = DurableJobWorkerService(repository)
            leased = worker.claim(
                tenant_id=tenant_a, worker_id="worker-a",
                occurred_at="2026-07-27T09:02:00Z",
                lease_expires_at="2026-07-27T09:10:00Z",
            )
            assert leased is not None and leased.job.id == workload.id
            leased = worker.heartbeat(
                leased, occurred_at="2026-07-27T09:03:00Z",
                lease_expires_at="2026-07-27T09:11:00Z",
            )
            leased = worker.commit_partition(
                leased, partition_key="p1", ordinal=1, completed_units=4,
                input_digest="3" * 64, output_digest="4" * 64,
                effect_reference="effect/p1", occurred_at="2026-07-27T09:04:00Z",
            )
            assert worker.completed_effects(leased)[0].partition_key == "p1"
            completed = worker.complete_partition(
                leased, partition_key="p2", ordinal=2, input_digest="5" * 64,
                output_digest="6" * 64, effect_reference="effect/p2",
                occurred_at="2026-07-27T09:05:00Z",
                output_manifest=JobOutputManifest(
                    schema_version=1, digest="7" * 64, reference="manifest/final"
                ),
            )
            assert completed.status.value == "completed"
            assert [effect.partition_key for effect in repository.list_partition_effects(
                tenant_id=tenant_a, job_id=workload.id
            )] == ["p1", "p2"]

            restart_job, _ = service.submit(
                replace(_submission(tenant_a), idempotency_key="restart-workload"),
                actor_id="submitter",
            )
            stale_leased = worker.claim(
                tenant_id=tenant_a, worker_id="worker-stale",
                occurred_at="2026-07-27T09:20:00Z",
                lease_expires_at="2026-07-27T09:21:00Z",
            )
            assert stale_leased is not None and stale_leased.job.id == restart_job.id
            stale_leased = worker.commit_partition(
                stale_leased, partition_key="p1", ordinal=1, completed_units=4,
                input_digest="8" * 64, output_digest="9" * 64,
                effect_reference="restart/p1", occurred_at="2026-07-27T09:20:30Z",
            )
            connection.close()
            connection = factory.connect()
            repository = PostgresDurableJobRepository(connection)
            resumed_worker = DurableJobWorkerService(repository)
            resumed = resumed_worker.claim(
                tenant_id=tenant_a, worker_id="worker-resumed",
                occurred_at="2026-07-27T09:21:00Z",
                lease_expires_at="2026-07-27T09:30:00Z",
            )
            assert resumed is not None and resumed.lease.generation == 2
            assert [effect.partition_key for effect in resumed_worker.completed_effects(resumed)] == ["p1"]
            with pytest.raises(PostgresJobConflictError):
                DurableJobWorkerService(repository).commit_partition(
                    stale_leased, partition_key="p2", ordinal=2, completed_units=8,
                    input_digest="a" * 64, output_digest="b" * 64,
                    effect_reference="stale/p2", occurred_at="2026-07-27T09:21:30Z",
                )
            restarted_completed = resumed_worker.complete_partition(
                resumed, partition_key="p2", ordinal=2, input_digest="a" * 64,
                output_digest="b" * 64, effect_reference="restart/p2",
                occurred_at="2026-07-27T09:22:00Z",
                output_manifest=JobOutputManifest(
                    schema_version=1, digest="c" * 64, reference="manifest/restarted"
                ),
            )
            assert [effect.effect_reference for effect in repository.list_partition_effects(
                tenant_id=tenant_a, job_id=restart_job.id
            )] == ["restart/p1", "restart/p2"]

            sqlite_path = tmp_path / "parity.db"
            run_migrations(sqlite_path)
            sqlite_connection = connect(sqlite_path, require_exists=True)
            try:
                sqlite_repository = SQLiteDurableJobRepository(sqlite_connection)
                sqlite_application = DurableJobApplicationService(sqlite_repository)
                sqlite_worker = DurableJobWorkerService(sqlite_repository)
                sqlite_job, _ = sqlite_application.submit(
                    replace(
                        _submission(tenant_a), job_id="sqlite-parity-job",
                        idempotency_key="sqlite-parity-key",
                    ),
                    actor_id="submitter",
                )
                sqlite_leased = sqlite_worker.claim(
                    tenant_id=tenant_a, worker_id="worker-stale",
                    occurred_at="2026-07-27T09:20:00Z",
                    lease_expires_at="2026-07-27T09:21:00Z",
                )
                assert sqlite_leased is not None
                sqlite_leased = sqlite_worker.commit_partition(
                    sqlite_leased, partition_key="p1", ordinal=1, completed_units=4,
                    input_digest="8" * 64, output_digest="9" * 64,
                    effect_reference="restart/p1", occurred_at="2026-07-27T09:20:30Z",
                )
                sqlite_connection.close()
                sqlite_connection = connect(sqlite_path, require_exists=True)
                sqlite_repository = SQLiteDurableJobRepository(sqlite_connection)
                sqlite_worker = DurableJobWorkerService(sqlite_repository)
                sqlite_resumed = sqlite_worker.claim(
                    tenant_id=tenant_a, worker_id="worker-resumed",
                    occurred_at="2026-07-27T09:21:00Z",
                    lease_expires_at="2026-07-27T09:30:00Z",
                )
                assert sqlite_resumed is not None
                sqlite_completed = sqlite_worker.complete_partition(
                    sqlite_resumed, partition_key="p2", ordinal=2, input_digest="a" * 64,
                    output_digest="b" * 64, effect_reference="restart/p2",
                    occurred_at="2026-07-27T09:22:00Z",
                    output_manifest=JobOutputManifest(
                        schema_version=1, digest="c" * 64, reference="manifest/restarted"
                    ),
                )
                sqlite_effects = sqlite_repository.list_partition_effects(
                    tenant_id=tenant_a, job_id=sqlite_job.id
                )
            finally:
                sqlite_connection.close()
            postgres_effects = repository.list_partition_effects(
                tenant_id=tenant_a, job_id=restart_job.id
            )
            def effect_semantics(effect: JobPartitionEffect) -> tuple[object, ...]:
                return (
                    effect.partition_key, effect.ordinal, effect.completed_units,
                    effect.input_digest, effect.output_digest, effect.effect_reference,
                )
            assert [effect_semantics(effect) for effect in postgres_effects] == [
                effect_semantics(effect) for effect in sqlite_effects
            ]
            assert (
                restarted_completed.status,
                restarted_completed.completed_units,
                restarted_completed.output_manifest,
            ) == (
                sqlite_completed.status,
                sqlite_completed.completed_units,
                sqlite_completed.output_manifest,
            )
            assert [row["reason_code"] for row in repository.list_transitions(
                tenant_id=tenant_a, job_id=restart_job.id
            )] == ["CREATED", "CLAIMED", "CHECKPOINTED", "LEASE_TAKEOVER", "FINISHED"]
            assert [row["action"] for row in repository.list_lease_events(
                tenant_id=tenant_a, job_id=restart_job.id
            )] == ["claimed", "taken_over", "released"]
            with pytest.raises(psycopg.Error, match="append-only"), admin.transaction():
                admin.execute(
                    "UPDATE reconforge.durable_job_partition_effects "
                    "SET output_digest=%s WHERE tenant_id=%s AND job_id=%s",
                    ("d" * 64, tenant_a, restart_job.id),
                )
            with pytest.raises(psycopg.Error, match="append-only"), admin.transaction():
                admin.execute(
                    "DELETE FROM reconforge.durable_job_transitions "
                    "WHERE tenant_id=%s AND job_id=%s",
                    (tenant_a, restart_job.id),
                )
        finally:
            connection.close()
    finally:
        admin.close()
