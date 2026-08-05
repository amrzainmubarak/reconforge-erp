from __future__ import annotations

import os
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Lock
from uuid import uuid4

import pytest

from reconforge.application.jobs import (
    DurableJobApplicationService,
    DurableJobLane,
    DurableJobWorkerService,
    GovernedDurableJobApplicationService,
    JobAuthorizationError,
    JobSubmission,
    RoundRobinDurableJobScheduler,
)
from reconforge.auth.policy import PolicyEvaluationContext
from reconforge.benchmark.postgres_durable_job_scale import (
    PostgresDurableJobScaleProfile,
    run_postgres_durable_job_scale_profile,
    verify_postgres_durable_job_scale_result,
)
from reconforge.benchmark.postgres_durable_job_scale import (
    default_profile as postgres_scale_profile,
)
from reconforge.benchmark.postgres_durable_job_scale import (
    hundred_k_profile as postgres_scale_100k_profile,
)
from reconforge.benchmark.postgres_durable_job_scale import (
    ten_k_profile as postgres_scale_10k_profile,
)
from reconforge.db import connect, run_migrations
from reconforge.domain.jobs import DurableJobBackpressureError, JobOutputManifest, JobPartitionEffect
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
            governed = GovernedDurableJobApplicationService(service)

            bounded_first_submission = replace(
                _submission(tenant_b),
                job_id="postgres-bounded-first-" + uuid4().hex[:8],
                idempotency_scope="postgres-bounded",
                idempotency_key="bounded-first-" + uuid4().hex[:8],
            )
            bounded_first, bounded_created = service.submit_bounded(
                bounded_first_submission,
                actor_id="bounded-submitter",
                max_queued_jobs=1,
            )
            bounded_replay, bounded_replay_created = service.submit_bounded(
                bounded_first_submission,
                actor_id="bounded-replay",
                max_queued_jobs=1,
            )
            assert bounded_created is True and bounded_replay_created is False
            assert bounded_replay == bounded_first
            bounded_second_submission = replace(
                _submission(tenant_b),
                job_id="postgres-bounded-second-" + uuid4().hex[:8],
                idempotency_scope="postgres-bounded",
                idempotency_key="bounded-second-" + uuid4().hex[:8],
            )
            with pytest.raises(DurableJobBackpressureError, match="queue capacity"):
                service.submit_bounded(
                    bounded_second_submission,
                    actor_id="bounded-submitter",
                    max_queued_jobs=1,
                )
            assert repository.get(tenant_id=tenant_b, job_id=bounded_second_submission.job_id) is None

            bounded_sibling_submission = replace(
                _submission(tenant_a),
                job_id="postgres-bounded-sibling-" + uuid4().hex[:8],
                idempotency_scope="postgres-bounded",
                idempotency_key="bounded-sibling-" + uuid4().hex[:8],
            )
            bounded_sibling, bounded_sibling_created = service.submit_bounded(
                bounded_sibling_submission,
                actor_id="bounded-submitter",
                max_queued_jobs=1,
            )
            assert bounded_sibling_created is True and bounded_sibling.tenant_id == tenant_a
            bounded_worker = DurableJobWorkerService(repository)
            bounded_lease = bounded_worker.claim(
                tenant_id=tenant_b,
                worker_id="bounded-worker",
                occurred_at="2026-07-27T09:59:01Z",
                lease_expires_at="2026-07-27T10:09:00Z",
            )
            assert bounded_lease is not None and bounded_lease.job.id == bounded_first.id
            bounded_retrying = bounded_worker.schedule_retry(
                bounded_lease,
                occurred_at="2026-07-27T09:59:02Z",
            )
            with pytest.raises(DurableJobBackpressureError, match="queue capacity"):
                service.submit_bounded(
                    bounded_second_submission,
                    actor_id="bounded-submitter",
                    max_queued_jobs=1,
                )
            bounded_retry_lease = bounded_worker.claim(
                tenant_id=tenant_b,
                worker_id="bounded-worker-recovery",
                occurred_at="2026-07-27T09:59:03Z",
                lease_expires_at="2026-07-27T10:09:00Z",
            )
            assert bounded_retry_lease is not None and bounded_retry_lease.job.id == bounded_retrying.id
            bounded_worker.cancel(bounded_retry_lease, occurred_at="2026-07-27T09:59:04Z")
            bounded_second, bounded_second_created = service.submit_bounded(
                bounded_second_submission,
                actor_id="bounded-submitter",
                max_queued_jobs=1,
            )
            assert bounded_second_created is True and bounded_second.status.value == "queued"
            service.cancel(
                tenant_id=tenant_a,
                job_id=bounded_sibling.id,
                actor_id="bounded-submitter",
                occurred_at="2026-07-27T09:59:05Z",
            )
            service.cancel(
                tenant_id=tenant_b,
                job_id=bounded_second.id,
                actor_id="bounded-submitter",
                occurred_at="2026-07-27T09:59:06Z",
            )

            # Bounded PostgreSQL parity/load slice: two tenant lanes contend
            # over real claims and generation-fenced partition effects. This
            # intentionally stays small and synthetic; it is not a capacity
            # or production-SLO claim.
            load_tenants = [tenant_a, tenant_b]
            load_jobs_per_tenant = 3
            load_partitions = 2
            load_jobs: list[tuple[str, str]] = []
            for tenant_index, tenant_id in enumerate(load_tenants):
                for job_index in range(load_jobs_per_tenant):
                    load_job_id = f"postgres-load-{tenant_index}-{job_index}-{uuid4().hex[:8]}"
                    load_jobs.append((tenant_id, load_job_id))
                    service.submit(
                        JobSubmission(
                            job_id=load_job_id,
                            idempotency_scope="postgres-load",
                            idempotency_key=load_job_id,
                            tenant_id=tenant_id,
                            workspace_id="workspace-a",
                            entity_id="entity-a",
                            input_digest="a" * 64,
                            config_digest="b" * 64,
                            worker_version="postgres-load-v1",
                            total_units=load_partitions,
                            retry_ceiling=2,
                            created_at="2026-07-27T10:00:00Z",
                        ),
                        actor_id="load-submitter",
                    )

            def drain_postgres_load(tenant_id: str, worker_id: str) -> int:
                worker_connection = factory.connect()
                try:
                    worker_repository = PostgresDurableJobRepository(worker_connection)
                    worker = DurableJobWorkerService(worker_repository)
                    completed = 0
                    while completed < load_jobs_per_tenant:
                        leased = worker.claim(
                            tenant_id=tenant_id,
                            worker_id=worker_id,
                            occurred_at="2026-07-27T10:01:00Z",
                            lease_expires_at="2026-07-27T10:11:00Z",
                        )
                        assert leased is not None
                        for ordinal in range(1, load_partitions + 1):
                            if ordinal == load_partitions:
                                worker.complete_partition(
                                    leased,
                                    partition_key=f"partition/{ordinal}",
                                    ordinal=ordinal,
                                    input_digest="c" * 64,
                                    output_digest="d" * 64,
                                    effect_reference=f"postgres-load/{leased.job.id}/{ordinal}",
                                    occurred_at=f"2026-07-27T10:01:0{ordinal}Z",
                                    output_manifest=JobOutputManifest(
                                        schema_version=1,
                                        digest="e" * 64,
                                        reference=f"manifest/{leased.job.id}",
                                    ),
                                )
                            else:
                                leased = worker.commit_partition(
                                    leased,
                                    partition_key=f"partition/{ordinal}",
                                    ordinal=ordinal,
                                    completed_units=ordinal,
                                    input_digest="c" * 64,
                                    output_digest="d" * 64,
                                    effect_reference=f"postgres-load/{leased.job.id}/{ordinal}",
                                    occurred_at=f"2026-07-27T10:01:0{ordinal}Z",
                                )
                        completed += 1
                    return completed
                finally:
                    worker_connection.close()

            with ThreadPoolExecutor(max_workers=len(load_tenants)) as executor:
                assert list(
                    executor.map(
                        lambda item: drain_postgres_load(*item),
                        [(tenant_id, f"postgres-load-worker-{index}") for index, tenant_id in enumerate(load_tenants)],
                    )
                ) == [load_jobs_per_tenant] * len(load_tenants)
            for tenant_id, load_job_id in load_jobs:
                effects = repository.list_partition_effects(tenant_id=tenant_id, job_id=load_job_id)
                assert len(effects) == load_partitions
                assert len({effect.partition_key for effect in effects}) == load_partitions
                loaded = repository.get(tenant_id=tenant_id, job_id=load_job_id)
                assert loaded is not None and loaded.status.value == "completed"

            # Bounded same-tenant claim contention: two real PostgreSQL
            # workers drain one queue concurrently. This proves SKIP LOCKED
            # claim ownership and no-duplicate effects without implying a
            # capacity, soak, or production-SLO result.
            contention_jobs_per_tenant = 4
            contention_partitions = 3
            contention_jobs: list[str] = []
            for job_index in range(contention_jobs_per_tenant):
                contention_job_id = f"postgres-contention-{job_index}-{uuid4().hex[:8]}"
                contention_jobs.append(contention_job_id)
                service.submit(
                    JobSubmission(
                        job_id=contention_job_id,
                        idempotency_scope="postgres-contention",
                        idempotency_key=contention_job_id,
                        tenant_id=tenant_a,
                        workspace_id="workspace-a",
                        entity_id="entity-a",
                        input_digest="f" * 64,
                        config_digest="0" * 64,
                        worker_version="postgres-contention-v1",
                        total_units=contention_partitions,
                        retry_ceiling=2,
                        created_at="2026-07-27T10:05:00Z",
                    ),
                    actor_id="contention-submitter",
                )
            completed_contention = 0
            contention_lock = Lock()

            def drain_contended_worker(worker_id: str) -> int:
                nonlocal completed_contention
                worker_connection = factory.connect()
                try:
                    worker_repository = PostgresDurableJobRepository(worker_connection)
                    worker = DurableJobWorkerService(worker_repository)
                    completed = 0
                    while True:
                        with contention_lock:
                            if completed_contention >= len(contention_jobs):
                                return completed
                        leased = worker.claim(
                            tenant_id=tenant_a,
                            worker_id=worker_id,
                            occurred_at="2026-07-27T10:06:00Z",
                            lease_expires_at="2026-07-27T10:16:00Z",
                        )
                        if leased is None:
                            time.sleep(0.01)
                            continue
                        for ordinal in range(1, contention_partitions + 1):
                            if ordinal == contention_partitions:
                                worker.complete_partition(
                                    leased,
                                    partition_key=f"contention/{ordinal}",
                                    ordinal=ordinal,
                                    input_digest="1" * 64,
                                    output_digest="2" * 64,
                                    effect_reference=f"postgres-contention/{leased.job.id}/{ordinal}",
                                    occurred_at=f"2026-07-27T10:06:0{ordinal}Z",
                                    output_manifest=JobOutputManifest(
                                        schema_version=1,
                                        digest="3" * 64,
                                        reference=f"manifest/contention/{leased.job.id}",
                                    ),
                                )
                            else:
                                leased = worker.commit_partition(
                                    leased,
                                    partition_key=f"contention/{ordinal}",
                                    ordinal=ordinal,
                                    completed_units=ordinal,
                                    input_digest="1" * 64,
                                    output_digest="2" * 64,
                                    effect_reference=f"postgres-contention/{leased.job.id}/{ordinal}",
                                    occurred_at=f"2026-07-27T10:06:0{ordinal}Z",
                                )
                        completed += 1
                        with contention_lock:
                            completed_contention += 1
                finally:
                    worker_connection.close()

            with ThreadPoolExecutor(max_workers=2) as executor:
                worker_counts = list(
                    executor.map(
                        drain_contended_worker,
                        ("postgres-contention-worker-a", "postgres-contention-worker-b"),
                    )
                )
            assert sum(worker_counts) == contention_jobs_per_tenant
            assert completed_contention == contention_jobs_per_tenant
            for contention_job_id in contention_jobs:
                effects = repository.list_partition_effects(tenant_id=tenant_a, job_id=contention_job_id)
                assert len(effects) == contention_partitions
                assert len({effect.partition_key for effect in effects}) == contention_partitions
                loaded = repository.get(tenant_id=tenant_a, job_id=contention_job_id)
                assert loaded is not None and loaded.status.value == "completed"

            retry_submission = JobSubmission(
                job_id="postgres-retry-" + uuid4().hex[:8],
                idempotency_scope="postgres-retry",
                idempotency_key="postgres-retry-key",
                tenant_id=tenant_a,
                workspace_id="workspace-a",
                entity_id="entity-a",
                input_digest="f" * 64,
                config_digest="7" * 64,
                worker_version="postgres-retry-v1",
                total_units=2,
                retry_ceiling=2,
                created_at="2026-07-27T10:20:00Z",
            )
            retry_job, retry_created = service.submit(retry_submission, actor_id="retry-submitter")
            assert retry_created is True
            retry_worker = DurableJobWorkerService(repository)
            retry_leased = retry_worker.claim(
                tenant_id=tenant_a,
                worker_id="retry-worker-fault",
                occurred_at="2026-07-27T10:20:01Z",
                lease_expires_at="2026-07-27T10:30:00Z",
            )
            assert retry_leased is not None and retry_leased.job.id == retry_job.id
            retry_leased = retry_worker.commit_partition(
                retry_leased,
                partition_key="retry/p1",
                ordinal=1,
                completed_units=1,
                input_digest="8" * 64,
                output_digest="9" * 64,
                effect_reference="retry/p1",
                occurred_at="2026-07-27T10:20:02Z",
            )
            retrying = retry_worker.schedule_retry(retry_leased, occurred_at="2026-07-27T10:20:03Z")
            assert retrying.status.value == "retrying" and retrying.retry_count == 1
            recovered = retry_worker.claim(
                tenant_id=tenant_a,
                worker_id="retry-worker-recovery",
                occurred_at="2026-07-27T10:20:04Z",
                lease_expires_at="2026-07-27T10:30:00Z",
            )
            assert recovered is not None and recovered.job.id == retry_job.id
            assert [effect.partition_key for effect in retry_worker.completed_effects(recovered)] == ["retry/p1"]
            retried_completed = retry_worker.complete_partition(
                recovered,
                partition_key="retry/p2",
                ordinal=2,
                input_digest="a" * 64,
                output_digest="b" * 64,
                effect_reference="retry/p2",
                occurred_at="2026-07-27T10:20:05Z",
                output_manifest=JobOutputManifest(
                    schema_version=1,
                    digest="c" * 64,
                    reference="manifest/retry",
                ),
            )
            assert retried_completed.status.value == "completed"
            assert retried_completed.retry_count == 1
            assert [row["reason_code"] for row in repository.list_transitions(
                tenant_id=tenant_a, job_id=retry_job.id
            )] == ["CREATED", "CLAIMED", "CHECKPOINTED", "TRANSIENT_FAILURE", "CLAIMED", "FINISHED"]
            governed_submission = replace(
                _submission(tenant_a), job_id="governed-postgres-job", idempotency_key="governed-postgres-key"
            )
            governed_context = PolicyEvaluationContext(
                user_id="governed-operator", username="governed-operator",
                user_permissions={"close.manage"}, tenant_id=tenant_a, workspace_id="workspace-a",
                authorized_tenant_ids=frozenset({tenant_a}),
                authorized_workspace_ids=frozenset({"workspace-a"}),
            )
            denied_context = replace(governed_context, user_permissions=set())
            with pytest.raises(JobAuthorizationError, match="permission_missing"):
                governed.submit(
                    governed_submission, actor_id="governed-operator",
                    policy_context=denied_context, required_permission="close.manage",
                )
            assert repository.get(tenant_id=tenant_a, job_id=governed_submission.job_id) is None
            governed_job, governed_created = governed.submit(
                governed_submission, actor_id="governed-operator",
                policy_context=governed_context, required_permission="close.manage",
            )
            assert governed_created is True and governed_job.tenant_id == tenant_a
            assert repository.get(tenant_id=tenant_b, job_id=governed_submission.job_id) is None
            governed_cancelled = governed.cancel(
                tenant_id=tenant_a, workspace_id="workspace-a", job_id=governed_submission.job_id,
                actor_id="governed-operator", occurred_at="2026-07-27T09:00:15Z",
                policy_context=governed_context, required_permission="close.manage",
            )
            assert governed_cancelled.status.value == "cancelled"
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


def _run_live_postgres_durable_job_scale_profile(
    profile_factory: Callable[[], PostgresDurableJobScaleProfile], *, id_prefix: str
) -> None:
    """Run one declared PostgreSQL scale tier with isolated synthetic tenants."""

    pytest.importorskip("psycopg")
    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if not app_user:
        pytest.skip("requires a non-privileged application role")
    factory = PostgresConnectionFactory(PostgresSettings(dsn=dsn, require_tls=False))
    admin_factory = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False))
    profile = profile_factory()
    tenants = tuple(f"jobs_scale_{uuid4().hex[:8]}_{index}" for index in range(profile.tenants))
    admin = admin_factory.connect()
    connection = None
    try:
        with admin.transaction():
            install_postgres_rls_schema(admin)
            install_postgres_durable_job_schema(admin)
            admin.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
            admin.execute(
                f"GRANT SELECT, INSERT, UPDATE ON reconforge.durable_jobs, "
                f"reconforge.durable_job_transitions, reconforge.durable_job_leases, "
                f"reconforge.durable_job_lease_events, reconforge.durable_job_partition_effects TO {app_user}"
            )
            admin.execute(f"GRANT DELETE ON reconforge.durable_job_leases TO {app_user}")
            for tenant in tenants:
                admin.execute("INSERT INTO reconforge.tenants (id, name) VALUES (%s, %s)", (tenant, tenant))
        connection = factory.connect()
        repository = PostgresDurableJobRepository(connection)
        result = run_postgres_durable_job_scale_profile(
            factory.connect,
            DurableJobApplicationService(repository),
            tenants,
            profile=profile,
            id_prefix=id_prefix + uuid4().hex[:8],
        )
        verify_postgres_durable_job_scale_result(result, profile=profile)
        print("postgres_durable_job_scale=" + result.to_manifest_text(), flush=True)
        assert result.completed_jobs == profile.jobs
        assert result.committed_partition_effects == profile.declared_partition_effects
        assert result.duplicate_partition_effects == 0
        assert result.final_queue_depth == result.final_running_depth == 0
    finally:
        if connection is not None:
            connection.close()
        admin.close()


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires live PostgreSQL")
def test_live_postgres_durable_job_bounded_multi_worker_scale_profile() -> None:
    """Exercise the repeatable 8-worker/256-effect PostgreSQL baseline."""

    _run_live_postgres_durable_job_scale_profile(postgres_scale_profile, id_prefix="PGSCALE-")


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires live PostgreSQL")
def test_live_postgres_durable_job_10k_multi_worker_scale_profile() -> None:
    """Exercise the declared 16-worker/10K-effect PostgreSQL tier."""

    _run_live_postgres_durable_job_scale_profile(postgres_scale_10k_profile, id_prefix="PGSCALE10K-")


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires live PostgreSQL")
def test_live_postgres_durable_job_100k_multi_worker_scale_profile() -> None:
    """Exercise the declared 16-worker/100K-effect PostgreSQL tier."""

    _run_live_postgres_durable_job_scale_profile(postgres_scale_100k_profile, id_prefix="PGSCALE100K-")


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires live PostgreSQL")
def test_live_postgres_round_robin_scheduler_is_lane_scoped_and_deterministic() -> None:
    pytest.importorskip("psycopg")
    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if not app_user:
        pytest.skip("requires a non-privileged application role")
    factory = PostgresConnectionFactory(PostgresSettings(dsn=dsn, require_tls=False))
    admin_factory = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False))
    tenant_id = "jobs_fair_" + uuid4().hex[:8]
    admin = admin_factory.connect()
    connection = None
    try:
        with admin.transaction():
            install_postgres_rls_schema(admin)
            install_postgres_durable_job_schema(admin)
            admin.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
            admin.execute(
                f"GRANT SELECT, INSERT, UPDATE ON reconforge.durable_jobs, "
                f"reconforge.durable_job_transitions, reconforge.durable_job_leases, "
                f"reconforge.durable_job_lease_events, reconforge.durable_job_partition_effects TO {app_user}"
            )
            admin.execute(f"GRANT DELETE ON reconforge.durable_job_leases TO {app_user}")
            admin.execute("INSERT INTO reconforge.tenants (id, name) VALUES (%s, %s)", (tenant_id, tenant_id))
        connection = factory.connect()
        repository = PostgresDurableJobRepository(connection)
        service = DurableJobApplicationService(repository)
        worker = DurableJobWorkerService(repository)
        lanes = (
            DurableJobLane(tenant_id, "workspace-fair-a", "entity-fair-a"),
            DurableJobLane(tenant_id, "workspace-fair-b", "entity-fair-b"),
        )
        for lane_index, lane in enumerate(lanes):
            for ordinal in range(3):
                service.submit(
                    replace(
                        _submission(tenant_id),
                        job_id=f"postgres-fair-{lane_index}-{ordinal}-{uuid4().hex[:6]}",
                        idempotency_scope="postgres-fair",
                        idempotency_key=f"fair-{lane_index}-{ordinal}-{uuid4().hex[:6]}",
                        workspace_id=lane.workspace_id,
                        entity_id=lane.entity_id,
                    ),
                    actor_id="fair-scheduler",
                )
        scheduler = RoundRobinDurableJobScheduler(worker, lanes)
        selected_lanes: list[DurableJobLane] = []
        for ordinal in range(6):
            scheduled = scheduler.claim(
                worker_id="fair-worker",
                occurred_at=f"2026-07-27T11:01:{ordinal:02d}Z",
                lease_expires_at=f"2026-07-27T11:02:{ordinal:02d}Z",
            )
            assert scheduled is not None
            selected_lanes.append(scheduled.lane)
            assert scheduled.leased_job.job.workspace_id == scheduled.lane.workspace_id
            assert scheduled.leased_job.job.entity_id == scheduled.lane.entity_id
            worker.cancel(scheduled.leased_job, occurred_at=f"2026-07-27T11:01:{30 + ordinal:02d}Z")
        assert selected_lanes == list(lanes) * 3
        assert scheduler.claim(
            worker_id="fair-worker",
            occurred_at="2026-07-27T11:04:00Z",
            lease_expires_at="2026-07-27T11:05:00Z",
        ) is None
    finally:
        if connection is not None:
            connection.close()
        admin.close()
