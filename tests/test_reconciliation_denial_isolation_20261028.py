"""Contract for reporting a single denied run without stopping other lanes.

This unit slice does not establish fairness across pages, restarts or real
PostgreSQL transactions. Those remain separate acceptance conditions.
"""

from __future__ import annotations

from contextlib import contextmanager
from decimal import Decimal
from typing import Any

import pytest

from reconforge.auth.policy import CentralPolicyEngine, PolicyEvaluationContext
from reconforge.infrastructure.postgres_reconciliation import (
    PostgresReconciliationBusyError,
    PostgresReconciliationRepository,
)
from reconforge.workers.policy import require_service_worker_policy
from reconforge.workers.postgres_reconciliation import (
    LocalDeterministicMatcherAdapter,
    PostgresReconciliationAuthorizationError,
    PostgresReconciliationPolicyDenied,
    PostgresReconciliationScheduler,
    PostgresReconciliationWorker,
    PostgresReconciliationWorkerError,
    PostgresReconciliationWorkerSettings,
    ReconciliationExecutionResult,
    ReconciliationProcessResult,
    ReconciliationWorkerRunSummary,
)
from tests.test_postgres_reconciliation import (
    _ConnectionFactory,
    _create_partitioned_reconciliation,
    _create_run,
    _ReconciliationConnection,
    _worker_manifest,
)


def _worker() -> PostgresReconciliationWorker:
    return PostgresReconciliationWorker(
        _ConnectionFactory(_ReconciliationConnection()),
        tenant_supplier=lambda: ["tenant_a", "tenant_b"],
        matcher=lambda _: ReconciliationExecutionResult(),
        settings=PostgresReconciliationWorkerSettings(
            worker_id="worker", batch_size=2, allow_unbound_hosted_policy=True,
        ),
    )


def test_typed_denial_does_not_hide_or_stop_other_runs_or_tenants(monkeypatch: pytest.MonkeyPatch) -> None:
    """One denial remains observable and cannot prevent allowed work on the page."""
    worker = _worker()
    visited: list[tuple[str, str]] = []

    def list_runs(_repository: object, *, tenant_id: str, **_kwargs: object) -> list[dict[str, object]]:
        ids = ("denied", "allowed-a") if tenant_id == "tenant_a" else ("allowed-b",)
        return [{"id": item, "rule_json": {"policy_amount": "1"}} for item in ids]

    def process_run(*, tenant_id: str, run_id: str, **_kwargs: object) -> ReconciliationProcessResult:
        visited.append((tenant_id, run_id))
        if run_id == "denied":
            raise PostgresReconciliationPolicyDenied("synthetic policy denial")
        return ReconciliationProcessResult(tenant_id=tenant_id, run_id=run_id, status="Complete")

    monkeypatch.setattr(PostgresReconciliationRepository, "list_runs", list_runs)
    monkeypatch.setattr(worker, "process_run", process_run)

    summaries = (worker.process_once(), worker.process_once())

    assert visited == [("tenant_a", "denied"), ("tenant_a", "allowed-a"), ("tenant_b", "allowed-b")] * 2
    for summary in summaries:
        assert summary.discovered == 3
        assert summary.completed == 2
        assert summary.denied == 1
        assert summary.failed == 0
        assert summary.skipped == 0


def test_unexpected_worker_error_is_not_classified_as_a_policy_denial(monkeypatch: pytest.MonkeyPatch) -> None:
    worker = _worker()
    monkeypatch.setattr(
        PostgresReconciliationRepository,
        "list_runs",
        lambda _repository, **_kwargs: [{"id": "run", "rule_json": {"policy_amount": "1"}}],
    )

    def process_run(**_kwargs: object) -> ReconciliationProcessResult:
        raise PostgresReconciliationWorkerError("synthetic supplier failure")

    monkeypatch.setattr(worker, "process_run", process_run)
    with pytest.raises(PostgresReconciliationWorkerError, match="synthetic supplier failure"):
        worker.process_once()


def test_unknown_amount_denial_is_counted_without_claim_or_state_mutation(caplog: pytest.LogCaptureFixture) -> None:
    connection = _ReconciliationConnection()
    _create_run(PostgresReconciliationRepository(connection))
    assert connection.run is not None
    before = dict(connection.run)

    def policy(tenant: str) -> PolicyEvaluationContext:
        return PolicyEvaluationContext(
            user_id="worker", username="worker", principal_type="service_account",
            user_permissions={"match.discover", "match.run"}, tenant_id=tenant,
            authorized_tenant_ids=frozenset({tenant}), amount=Decimal("1"), maximum_amount=Decimal("10"),
        )

    worker = PostgresReconciliationWorker(
        _ConnectionFactory(connection), tenant_supplier=lambda: ["tenant_a"],
        matcher=lambda _: ReconciliationExecutionResult(),
        settings=PostgresReconciliationWorkerSettings(
            worker_id="worker", permission_manifest=_worker_manifest("worker"),
            discovery_policy_permission="match.discover", policy_context_supplier=policy,
        ),
    )
    summary = worker.process_once()
    assert (summary.denied, summary.completed, summary.failed, summary.skipped) == (1, 0, 0, 0)
    assert connection.run == before
    assert connection.results == [] and connection.exceptions == [] and connection.checkpoints == []
    assert "reconciliation_policy_denials" in caplog.text
    assert "tenant_a" not in caplog.text and "run-a" not in caplog.text


def test_claim_recheck_supplier_failure_is_not_silently_classified_as_denial() -> None:
    connection = _ReconciliationConnection()
    _create_run(PostgresReconciliationRepository(connection))
    assert connection.run is not None
    before = dict(connection.run)
    calls = 0

    def policy(tenant: str) -> PolicyEvaluationContext:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise ValueError("synthetic supplier offline")
        return PolicyEvaluationContext(
            user_id="worker", username="worker", principal_type="service_account",
            user_permissions={"match.discover", "match.run"}, tenant_id=tenant,
            authorized_tenant_ids=frozenset({tenant}),
        )

    worker = PostgresReconciliationWorker(
        _ConnectionFactory(connection), tenant_supplier=lambda: ["tenant_a"],
        matcher=lambda _: ReconciliationExecutionResult(),
        settings=PostgresReconciliationWorkerSettings(
            worker_id="worker", permission_manifest=_worker_manifest("worker"),
            discovery_policy_permission="match.discover", policy_context_supplier=policy,
        ),
    )
    with pytest.raises(PostgresReconciliationWorkerError, match="Unable to resolve worker policy context safely") as exc:
        worker.process_once()
    assert not isinstance(exc.value, PostgresReconciliationPolicyDenied)
    assert calls == 3 and connection.run == before


def test_claim_recheck_audit_failure_is_not_denial_or_run_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    from reconforge.workers import policy as worker_policy

    connection = _ReconciliationConnection()
    _create_run(PostgresReconciliationRepository(connection))
    assert connection.run is not None
    before = dict(connection.run)
    calls = 0
    original_audit = worker_policy.audit_policy_decision

    def failing_audit(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise OSError("synthetic audit failure")
        return original_audit(*args, **kwargs)  # type: ignore[arg-type]

    def policy(tenant: str) -> PolicyEvaluationContext:
        return PolicyEvaluationContext(
            user_id="worker", username="worker", principal_type="service_account",
            user_permissions={"match.discover", "match.run"}, tenant_id=tenant,
            authorized_tenant_ids=frozenset({tenant}),
        )

    worker = PostgresReconciliationWorker(
        _ConnectionFactory(connection), tenant_supplier=lambda: ["tenant_a"],
        matcher=lambda _: ReconciliationExecutionResult(),
        settings=PostgresReconciliationWorkerSettings(
            worker_id="worker", permission_manifest=_worker_manifest("worker"),
            discovery_policy_permission="match.discover", policy_context_supplier=policy,
        ),
    )
    monkeypatch.setattr(worker_policy, "audit_policy_decision", failing_audit)
    with pytest.raises(PostgresReconciliationWorkerError, match="record worker policy decision") as exc:
        worker.process_once()
    assert not isinstance(exc.value, PostgresReconciliationPolicyDenied)
    assert calls == 3 and connection.run == before
    assert connection.results == [] and connection.exceptions == [] and connection.checkpoints == []


def test_claim_recheck_policy_engine_failure_remains_an_authorization_error(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = _ReconciliationConnection()
    _create_run(PostgresReconciliationRepository(connection))
    assert connection.run is not None
    before = dict(connection.run)
    calls = 0
    evaluate = CentralPolicyEngine.evaluate

    def failing_evaluate(self: CentralPolicyEngine, *args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise RuntimeError("synthetic evaluator failure")
        return evaluate(self, *args, **kwargs)

    def policy(tenant: str) -> PolicyEvaluationContext:
        return PolicyEvaluationContext(
            user_id="worker", username="worker", principal_type="service_account",
            user_permissions={"match.discover", "match.run"}, tenant_id=tenant,
            authorized_tenant_ids=frozenset({tenant}),
        )

    worker = PostgresReconciliationWorker(
        _ConnectionFactory(connection), tenant_supplier=lambda: ["tenant_a"],
        matcher=lambda _: ReconciliationExecutionResult(),
        settings=PostgresReconciliationWorkerSettings(
            worker_id="worker", permission_manifest=_worker_manifest("worker"),
            discovery_policy_permission="match.discover", policy_context_supplier=policy,
        ),
    )
    monkeypatch.setattr(CentralPolicyEngine, "evaluate", failing_evaluate)
    with pytest.raises(PostgresReconciliationWorkerError, match="evaluate worker policy safely") as exc:
        worker.process_once()
    assert not isinstance(exc.value, PostgresReconciliationPolicyDenied)
    assert calls == 3 and connection.run == before
    assert connection.results == [] and connection.exceptions == [] and connection.checkpoints == []


@pytest.mark.parametrize("failure_site", ["evaluator", "audit"])
def test_shared_guard_preserves_original_exception_for_legacy_callers(
    monkeypatch: pytest.MonkeyPatch, failure_site: str,
) -> None:
    from reconforge.workers import policy as worker_policy

    original = RuntimeError("synthetic policy infrastructure failure")
    if failure_site == "evaluator":
        def fail_evaluate(*_args: Any, **_kwargs: Any) -> Any:
            raise original
        monkeypatch.setattr(CentralPolicyEngine, "evaluate", fail_evaluate)
    else:
        def fail_audit(*_args: Any, **_kwargs: Any) -> Any:
            raise original
        monkeypatch.setattr(worker_policy, "audit_policy_decision", fail_audit)

    def policy(tenant: str) -> PolicyEvaluationContext:
        return PolicyEvaluationContext(
            user_id="worker", username="worker", principal_type="service_account",
            user_permissions={"match.run"}, tenant_id=tenant, authorized_tenant_ids=frozenset({tenant}),
        )

    with pytest.raises(RuntimeError, match="synthetic policy infrastructure failure") as exc:
        require_service_worker_policy(
            tenant_id="tenant", worker_id="worker", actor_id="worker", policy_context_supplier=policy,
            policy_permission="match.run", surface="test.legacy", error_factory=ValueError,
        )
    assert exc.value is original


@pytest.mark.parametrize(
    "error_type",
    [PostgresReconciliationPolicyDenied, PostgresReconciliationAuthorizationError, PostgresReconciliationBusyError],
)
@pytest.mark.parametrize("partitioned", [False, True])
def test_matcher_errors_after_claim_are_failures_not_policy_denials(error_type: type[Exception], partitioned: bool) -> None:
    connection = _ReconciliationConnection()
    if partitioned:
        _create_partitioned_reconciliation(connection, run_id="run-a")
    else:
        _create_run(PostgresReconciliationRepository(connection))
    adapter = LocalDeterministicMatcherAdapter()

    class Matcher:
        def __call__(self, _context: Any) -> ReconciliationExecutionResult:
            raise error_type("synthetic post-claim matcher failure")

        def iter_partition_results(self, context: Any, *, completed_partition_keys: frozenset[str] = frozenset()) -> Any:
            for partition in adapter.iter_partition_results(context, completed_partition_keys=completed_partition_keys):
                yield partition
                raise error_type("synthetic post-claim matcher failure")

    worker = PostgresReconciliationWorker(
        _ConnectionFactory(connection), tenant_supplier=lambda: ["tenant_a"], matcher=Matcher(),
        settings=PostgresReconciliationWorkerSettings(worker_id="worker", allow_unbound_hosted_policy=True),
    )
    result = worker.process_once()
    assert (result.failed, result.denied, result.completed, result.skipped) == (1, 0, 0, 0)
    assert connection.run is not None and connection.run["execution_status"] == "Failed"
    if partitioned:
        assert len(connection.checkpoints) == 1 and len(connection.results) == 1
    else:
        assert connection.checkpoints == [] and connection.results == []


def test_busy_before_claim_remains_skipped_and_leaves_run_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = _ReconciliationConnection()
    _create_run(PostgresReconciliationRepository(connection))
    assert connection.run is not None
    before = dict(connection.run)

    def busy(*_args: Any, **_kwargs: Any) -> Any:
        raise PostgresReconciliationBusyError("synthetic busy claim")

    monkeypatch.setattr(PostgresReconciliationRepository, "claim_run", busy)
    worker = PostgresReconciliationWorker(
        _ConnectionFactory(connection), tenant_supplier=lambda: ["tenant_a"],
        matcher=lambda _: ReconciliationExecutionResult(),
        settings=PostgresReconciliationWorkerSettings(worker_id="worker", allow_unbound_hosted_policy=True),
    )
    summary = worker.process_once()
    assert (summary.skipped, summary.failed, summary.denied, summary.completed) == (1, 0, 0, 0)
    assert connection.run == before
    assert connection.results == [] and connection.exceptions == [] and connection.checkpoints == []


def test_scheduler_and_run_preserve_denial_count_across_workers_and_cycles() -> None:
    class Worker:
        def process_once(self) -> ReconciliationWorkerRunSummary:
            return ReconciliationWorkerRunSummary(
                cycles=1, discovered=2, completed=1, failed=0, cancelled=0, skipped=0, denied=1,
            )

    class Telemetry:
        def __init__(self) -> None:
            self.jobs: list[dict[str, object]] = []

        @contextmanager
        def span(self, _name: str, _attributes: dict[str, object]) -> Any:
            yield None

        def record_job(self, attributes: dict[str, object]) -> None:
            self.jobs.append(attributes)

    telemetry = Telemetry()
    scheduler = PostgresReconciliationScheduler(
        lambda _worker_id: Worker(), worker_ids=["a", "b"], poll_interval_seconds=0,
        observability=telemetry,  # type: ignore[arg-type]
    )
    summary = scheduler.run(max_cycles=2)
    assert (summary.cycles, summary.denied, summary.completed, summary.skipped) == (4, 4, 4, 0)
    assert [job["reconforge.result"] for job in telemetry.jobs] == ["policy_denied"] * 4
