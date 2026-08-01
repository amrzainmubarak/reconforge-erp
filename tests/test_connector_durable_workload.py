from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from reconforge.application.jobs import DurableJobApplicationService, DurableJobWorkerService, JobSubmission, LeasedJob
from reconforge.connectors.network import ConnectorNetworkError, NetworkConnectorExecutor, NetworkResponse
from reconforge.connectors.workload import DurableConnectorWorkload
from reconforge.db import connect, run_migrations
from reconforge.domain.jobs import JobStatus
from reconforge.infrastructure.object_storage import (
    LocalObjectStorageSettings,
    LocalObjectStore,
    ObjectStorageConflictError,
)
from reconforge.infrastructure.sqlite_jobs import SQLiteDurableJobRepository
from tests.test_connector_network import _registration, _Secrets, _Transport


def _submission(job_id: str, registration_digest: str) -> JobSubmission:
    return JobSubmission(
        job_id=job_id,
        idempotency_scope="tenant/workspace/connector-registration",
        idempotency_key="connector-run-1",
        tenant_id="TENANT-1",
        workspace_id="WORKSPACE-1",
        entity_id="ENTITY-1",
        input_digest="a" * 64,
        config_digest=registration_digest,
        worker_version="connector-worker/1.0.0",
        total_units=2,
        retry_ceiling=2,
        created_at="2026-07-30T06:00:00Z",
    )


@dataclass
class _RunResult:
    output_digest: str
    effects: list[tuple[str, str, str]]
    cursors_sent: list[str | None]


def _run(root: Path, *, restart: bool) -> _RunResult:
    registration = _registration()
    database_path = root / "jobs.db"
    object_root = (root / "objects").resolve()
    run_migrations(database_path)
    connection = connect(database_path, require_exists=True)
    repository = SQLiteDurableJobRepository(connection)
    application = DurableJobApplicationService(repository)
    worker = DurableJobWorkerService(repository)
    queued, created = application.submit(
        _submission("CONNECTOR-JOB-1", registration.digest), actor_id="scheduler-1"
    )
    assert created
    leased = worker.claim(
        tenant_id="TENANT-1",
        worker_id="worker-1",
        occurred_at="2026-07-30T06:00:01Z",
        lease_expires_at="2026-07-30T06:00:03Z" if restart else "2026-07-30T06:00:10Z",
    )
    assert leased is not None
    transport = _Transport(
        [NetworkResponse(200, b'{"page":1}', "cursor-2"), NetworkResponse(200, b'{"page":2}', None)]
    )
    workload = DurableConnectorWorkload(
        NetworkConnectorExecutor(transport, secret_resolver=_Secrets()),
        LocalObjectStore(LocalObjectStorageSettings(root=object_root)),
    )
    first = workload.run_page(
        worker,
        leased,
        registration,
        ordinal=1,
        idempotency_key="CONNECTOR-JOB-1/page/1",
        cursor=None,
        occurred_at="2026-07-30T06:00:02Z",
        final=False,
    )
    assert first.next_cursor == "cursor-2"
    if restart:
        connection.close()
        connection = connect(database_path, require_exists=True)
        repository = SQLiteDurableJobRepository(connection)
        worker = DurableJobWorkerService(repository)
        leased = worker.claim(
            tenant_id="TENANT-1",
            worker_id="worker-2",
            occurred_at="2026-07-30T06:00:03Z",
            lease_expires_at="2026-07-30T06:00:08Z",
        )
        assert leased is not None
    else:
        assert isinstance(first.job, LeasedJob)
        leased = first.job
    cursor = workload.resume_cursor(worker, leased)
    assert cursor == "cursor-2"
    second = workload.run_page(
        worker,
        leased,
        registration,
        ordinal=2,
        idempotency_key="CONNECTOR-JOB-1/page/2",
        cursor=cursor,
        occurred_at="2026-07-30T06:00:04Z" if restart else "2026-07-30T06:00:03Z",
        final=True,
    )
    assert second.job.status is JobStatus.COMPLETED
    assert second.job.output_manifest is not None
    effects = repository.list_partition_effects(tenant_id="TENANT-1", job_id=queued.id)
    result = _RunResult(
        output_digest=second.job.output_manifest.digest,
        effects=[(effect.partition_key, effect.input_digest, effect.output_digest) for effect in effects],
        cursors_sent=[call[1].get("X-ReconForge-Cursor") for call in transport.calls],
    )
    connection.close()
    return result


def test_connector_workload_resume_matches_uninterrupted_and_skips_committed_page(tmp_path: Path) -> None:
    uninterrupted = _run(tmp_path / "uninterrupted", restart=False)
    resumed = _run(tmp_path / "resumed", restart=True)
    assert resumed == uninterrupted
    assert resumed.cursors_sent == [None, "cursor-2"]
    assert len(resumed.effects) == 2


def test_connector_workload_rejects_registration_drift_before_network(tmp_path: Path) -> None:
    registration = _registration()
    database_path = tmp_path / "jobs.db"
    run_migrations(database_path)
    connection = connect(database_path, require_exists=True)
    repository = SQLiteDurableJobRepository(connection)
    queued, _ = DurableJobApplicationService(repository).submit(
        _submission("CONNECTOR-JOB-DRIFT", "b" * 64), actor_id="scheduler-1"
    )
    worker = DurableJobWorkerService(repository)
    leased = worker.claim(
        tenant_id="TENANT-1",
        worker_id="worker-1",
        occurred_at="2026-07-30T06:00:01Z",
        lease_expires_at="2026-07-30T06:00:05Z",
    )
    assert leased is not None and leased.job.id == queued.id
    transport = _Transport([])
    workload = DurableConnectorWorkload(
        NetworkConnectorExecutor(transport, secret_resolver=_Secrets()),
        LocalObjectStore(LocalObjectStorageSettings(root=(tmp_path / "objects").resolve())),
    )
    with pytest.raises(ConnectorNetworkError, match="registration_digest_mismatch"):
        workload.run_page(
            worker,
            leased,
            registration,
            ordinal=1,
            idempotency_key="drift/page/1",
            cursor=None,
            occurred_at="2026-07-30T06:00:02Z",
            final=False,
        )
    assert transport.calls == []
    connection.close()


def test_connector_workload_recovers_identical_object_after_uncertain_put(tmp_path: Path) -> None:
    registration = _registration()
    database_path = tmp_path / "jobs.db"
    run_migrations(database_path)
    connection = connect(database_path, require_exists=True)
    repository = SQLiteDurableJobRepository(connection)
    DurableJobApplicationService(repository).submit(
        _submission("CONNECTOR-JOB-PUT", registration.digest), actor_id="scheduler-1"
    )
    worker = DurableJobWorkerService(repository)
    leased = worker.claim(
        tenant_id="TENANT-1",
        worker_id="worker-1",
        occurred_at="2026-07-30T06:00:01Z",
        lease_expires_at="2026-07-30T06:00:05Z",
    )
    assert leased is not None
    local = LocalObjectStore(LocalObjectStorageSettings(root=(tmp_path / "objects").resolve()))

    class _UncertainPutStore:
        def put_bytes(self, *args: object, **kwargs: object) -> object:
            local.put_bytes(*args, **kwargs)  # type: ignore[arg-type]
            raise ObjectStorageConflictError("synthetic uncertain completion")

        def get_bytes(self, *args: object, **kwargs: object) -> object:
            return local.get_bytes(*args, **kwargs)  # type: ignore[arg-type]

    workload = DurableConnectorWorkload(
        NetworkConnectorExecutor(
            _Transport([NetworkResponse(200, b'{"page":1}', "cursor-2")]), secret_resolver=_Secrets()
        ),
        _UncertainPutStore(),  # type: ignore[arg-type]
    )
    committed = workload.run_page(
        worker,
        leased,
        registration,
        ordinal=1,
        idempotency_key="uncertain/page/1",
        cursor=None,
        occurred_at="2026-07-30T06:00:02Z",
        final=False,
    )
    assert isinstance(committed.job, LeasedJob)
    assert committed.job.job.completed_units == 1
    assert len(worker.completed_effects(committed.job)) == 1
    connection.close()
