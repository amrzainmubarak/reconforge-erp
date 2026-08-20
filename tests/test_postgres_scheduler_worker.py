from __future__ import annotations

from datetime import UTC, datetime

import pytest

from reconforge.application.scheduler import ScheduleProcessResult
from reconforge.auth.policy import PolicyEvaluationContext
from reconforge.workers import postgres_scheduler as worker_module
from reconforge.workers.postgres_scheduler import (
    PostgresSchedulerWorker,
    PostgresSchedulerWorkerError,
    PostgresSchedulerWorkerSettings,
)


class _Connection:
    def __init__(self, number: int) -> None:
        self.number = number
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _Factory:
    def __init__(self) -> None:
        self.connections: list[_Connection] = []

    def connect(self) -> _Connection:
        connection = _Connection(len(self.connections) + 1)
        self.connections.append(connection)
        return connection


def test_scheduler_worker_uses_stable_tenant_order_one_clock_and_fresh_connections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = _Factory()
    calls: list[tuple[int, str, str, datetime, int]] = []

    class Service:
        def __init__(self, repository: object) -> None:
            self.repository = repository

        def process_due(
            self, *, tenant_id: str, worker_id: str, now: datetime, limit: int
        ) -> ScheduleProcessResult:
            connection = self.repository.connection  # type: ignore[attr-defined]
            calls.append((connection.number, tenant_id, worker_id, now, limit))
            return ScheduleProcessResult(1, 1, 2, 1, 0, 1, 0, 0)

    monkeypatch.setattr(worker_module, "SchedulerApplicationService", Service)
    worker = PostgresSchedulerWorker(
        factory,
        tenant_supplier=lambda: ("tenant-b", "tenant-a", "tenant-a"),
        settings=PostgresSchedulerWorkerSettings(
            worker_id="scheduler-worker", poll_interval_seconds=0, batch_size=25
        ),
        clock=lambda: datetime(2026, 7, 29, 12, 0, 0, 987654, tzinfo=UTC),
    )
    summary = worker.run(max_cycles=2)
    assert [call[1] for call in calls] == ["tenant-a", "tenant-b", "tenant-a", "tenant-b"]
    assert {call[3] for call in calls} == {datetime(2026, 7, 29, 12, tzinfo=UTC)}
    assert all(call[2:] == ("scheduler-worker", datetime(2026, 7, 29, 12, tzinfo=UTC), 25) for call in calls)
    assert len(factory.connections) == 4 and all(connection.closed for connection in factory.connections)
    assert (summary.cycles, summary.tenants_processed, summary.dispatched, summary.skipped) == (2, 4, 4, 4)


def test_scheduler_worker_fails_closed_for_invalid_clock_enumeration_and_bounds() -> None:
    factory = _Factory()
    worker = PostgresSchedulerWorker(
        factory,
        tenant_supplier=lambda: ("INVALID TENANT",),
        settings=PostgresSchedulerWorkerSettings(worker_id="scheduler-worker", max_tenants=1),
    )
    with pytest.raises(PostgresSchedulerWorkerError, match="enumerate"):
        worker.process_once()
    naive = PostgresSchedulerWorker(
        factory,
        tenant_supplier=tuple,
        settings=PostgresSchedulerWorkerSettings(worker_id="scheduler-worker"),
        clock=lambda: datetime(2026, 7, 29),
    )
    with pytest.raises(PostgresSchedulerWorkerError, match="timezone-aware"):
        naive.process_once()
    with pytest.raises(PostgresSchedulerWorkerError, match="max_cycles"):
        naive.run(max_cycles=0)


def test_scheduler_worker_policy_denies_before_connection_access() -> None:
    class _NeverConnect:
        def connect(self) -> _Connection:
            raise AssertionError("policy denial must precede connection access")

    worker = PostgresSchedulerWorker(
        _NeverConnect(),
        tenant_supplier=lambda: ("tenant_a",),
        settings=PostgresSchedulerWorkerSettings(
            worker_id="scheduler-policy-worker",
            policy_context_supplier=lambda tenant: PolicyEvaluationContext(
                user_id="scheduler-policy-worker",
                username="scheduler-policy-worker",
                user_permissions=set(),
                principal_type="service_account",
                tenant_id=tenant,
                authorized_tenant_ids=frozenset({tenant}),
            ),
        ),
    )
    with pytest.raises(PostgresSchedulerWorkerError, match="permission_missing"):
        worker.process_once()


def test_scheduler_worker_policy_allows_scoped_service_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    factory = _Factory()

    class Service:
        def __init__(self, repository: object) -> None:
            self.repository = repository

        def process_due(
            self, *, tenant_id: str, worker_id: str, now: datetime, limit: int
        ) -> ScheduleProcessResult:
            return ScheduleProcessResult(1, 1, 1, 1, 0, 0, 0, 0)

    monkeypatch.setattr(worker_module, "SchedulerApplicationService", Service)
    worker = PostgresSchedulerWorker(
        factory,
        tenant_supplier=lambda: ("tenant_a",),
        settings=PostgresSchedulerWorkerSettings(
            worker_id="scheduler-policy-worker",
            policy_context_supplier=lambda tenant: PolicyEvaluationContext(
                user_id="scheduler-policy-worker",
                username="scheduler-policy-worker",
                user_permissions={"schedule.run"},
                principal_type="service_account",
                tenant_id=tenant,
                authorized_tenant_ids=frozenset({tenant}),
            ),
        ),
    )
    result = worker.process_once()
    assert result[0].dispatched == 1


def test_scheduler_worker_rechecks_policy_before_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    factory = _Factory()
    policy_calls = 0
    dispatched = 0

    class Service:
        def __init__(self, repository: object) -> None:
            self.repository = repository

        def process_due(
            self, *, tenant_id: str, worker_id: str, now: datetime, limit: int
        ) -> ScheduleProcessResult:
            nonlocal dispatched
            dispatched += 1
            return ScheduleProcessResult(1, 1, 1, 1, 0, 0, 0, 0)

    def policy_context(tenant: str) -> PolicyEvaluationContext:
        nonlocal policy_calls
        policy_calls += 1
        permissions = {"schedule.run"} if policy_calls == 1 else set()
        return PolicyEvaluationContext(
            user_id="scheduler-revocation-worker",
            username="scheduler-revocation-worker",
            user_permissions=permissions,
            principal_type="service_account",
            tenant_id=tenant,
            authorized_tenant_ids=frozenset({tenant}),
        )

    monkeypatch.setattr(worker_module, "SchedulerApplicationService", Service)
    worker = PostgresSchedulerWorker(
        factory,
        tenant_supplier=lambda: ("tenant_a",),
        settings=PostgresSchedulerWorkerSettings(
            worker_id="scheduler-revocation-worker",
            policy_context_supplier=policy_context,
            poll_interval_seconds=0,
        ),
        clock=lambda: datetime(2026, 7, 29, 12, tzinfo=UTC),
    )

    with pytest.raises(PostgresSchedulerWorkerError, match="permission_missing"):
        worker.process_once()

    assert policy_calls == 2
    assert dispatched == 0
    assert len(factory.connections) == 1 and factory.connections[0].closed


def test_scheduler_worker_scope_lane_requires_exact_policy_and_passes_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = _Factory()
    calls: list[tuple[str, str | None, str | None]] = []

    class Service:
        def __init__(self, repository: object) -> None:
            self.repository = repository

        def process_due(
            self,
            *,
            tenant_id: str,
            worker_id: str,
            now: datetime,
            limit: int,
            workspace_id: str | None = None,
            entity_id: str | None = None,
        ) -> ScheduleProcessResult:
            calls.append((tenant_id, workspace_id, entity_id))
            return ScheduleProcessResult(1, 1, 1, 1, 0, 0, 0, 0)

    monkeypatch.setattr(worker_module, "SchedulerApplicationService", Service)

    def policy_context(tenant: str, workspace: str | None, entity: str | None) -> PolicyEvaluationContext:
        return PolicyEvaluationContext(
            user_id="scoped-scheduler",
            username="scoped-scheduler",
            user_permissions={"schedule.run"},
            principal_type="service_account",
            tenant_id=tenant,
            workspace_id=workspace,
            entity_id=entity,
            authorized_tenant_ids=frozenset({tenant}),
            authorized_workspace_ids=frozenset({workspace}) if workspace else frozenset(),
            authorized_entity_ids=frozenset({entity}) if entity else frozenset(),
        )

    worker = PostgresSchedulerWorker(
        factory,
        tenant_supplier=tuple,
        settings=PostgresSchedulerWorkerSettings(
            worker_id="scoped-scheduler",
            policy_context_scope_supplier=policy_context,
            scope_supplier=lambda: (("tenant_a", "workspace-a", "entity-a"),),
            poll_interval_seconds=0,
        ),
        clock=lambda: datetime(2026, 7, 29, 12, tzinfo=UTC),
    )

    result = worker.process_once()

    assert result[0].dispatched == 1
    assert calls == [("tenant_a", "workspace-a", "entity-a")]
    assert len(factory.connections) == 1 and factory.connections[0].closed


def test_scheduler_worker_rejects_entity_lane_without_workspace_before_connection() -> None:
    class _NeverConnect:
        def connect(self) -> _Connection:
            raise AssertionError("invalid scope must be rejected before connection access")

    worker = PostgresSchedulerWorker(
        _NeverConnect(),
        tenant_supplier=tuple,
        settings=PostgresSchedulerWorkerSettings(
            worker_id="scoped-scheduler",
            policy_context_scope_supplier=lambda tenant, workspace, entity: PolicyEvaluationContext(
                user_id="scoped-scheduler",
                username="scoped-scheduler",
                user_permissions={"schedule.run"},
                principal_type="service_account",
                tenant_id=tenant,
                workspace_id=workspace,
                entity_id=entity,
                authorized_tenant_ids=frozenset({tenant}),
                authorized_workspace_ids=frozenset({workspace}) if workspace else frozenset(),
                authorized_entity_ids=frozenset({entity}) if entity else frozenset(),
            ),
            scope_supplier=lambda: (("tenant_a", None, "entity-a"),),
        ),
    )
    with pytest.raises(PostgresSchedulerWorkerError, match="requires workspace scope"):
        worker.process_once()
