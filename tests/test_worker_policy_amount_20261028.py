"""Worker authorization must distinguish unknown amounts from omitted amounts."""

from dataclasses import replace
from decimal import Decimal

import pytest

from reconforge.auth.policy import PolicyEvaluationContext
from reconforge.deployment import WorkerPermissionManifest
from reconforge.infrastructure.postgres_reconciliation import PostgresReconciliationRepository
from reconforge.workers.policy import UnknownWorkerPolicyAmount, require_service_worker_policy
from reconforge.workers.postgres_reconciliation import (
    PostgresReconciliationPolicyDenied,
    PostgresReconciliationWorker,
    PostgresReconciliationWorkerError,
    PostgresReconciliationWorkerSettings,
    ReconciliationExecutionResult,
)
from tests.test_postgres_reconciliation import (
    _ConnectionFactory,
    _create_run,
    _ReconciliationConnection,
    _worker_manifest,
)


def _supplier(tenant: str) -> PolicyEvaluationContext:
    return PolicyEvaluationContext(
        user_id="worker",
        username="worker",
        user_permissions={"match.discover", "match.run"},
        principal_type="service_account",
        tenant_id=tenant,
        authorized_tenant_ids=frozenset({tenant}),
        amount=Decimal("1"),
        maximum_amount=Decimal("10"),
    )


def _require(**kwargs: object) -> None:
    require_service_worker_policy(
        tenant_id="tenant",
        worker_id="worker",
        actor_id="worker",
        policy_context_supplier=_supplier,
        policy_permission="match.run",
        surface="test.worker",
        error_factory=ValueError,
        **kwargs,  # type: ignore[arg-type]
    )


def test_explicit_none_preserves_legacy_supplier_contract() -> None:
    _require(amount=None)


def test_omitted_amount_preserves_supplier_contract() -> None:
    _require()


def test_explicit_unknown_amount_does_not_reuse_supplier_amount() -> None:
    with pytest.raises(ValueError, match="amount_missing_for_bounded_policy"):
        _require(amount=UnknownWorkerPolicyAmount.UNKNOWN)


def test_explicit_amount_is_evaluated_instead_of_supplier_amount() -> None:
    _require(amount=Decimal("0"))
    _require(amount=Decimal("10"))
    with pytest.raises(ValueError, match="amount_above_ceiling"):
        _require(amount=Decimal("11"))
    with pytest.raises(ValueError, match="amount is invalid"):
        _require(amount=Decimal("NaN"))


def test_worker_discovery_omits_amount_but_unknown_run_is_denied() -> None:
    manifest = WorkerPermissionManifest(
        worker_id="worker", principal_id="worker", discovery_permission="match.discover",
        execution_permission="match.run", granted_permissions=("match.discover", "match.run"),
        scope="tenant:tenant",
    )
    worker = PostgresReconciliationWorker(
        object(),  # type: ignore[arg-type]
        tenant_supplier=lambda: ["tenant"],
        matcher=lambda _: ReconciliationExecutionResult(),
        settings=PostgresReconciliationWorkerSettings(
            worker_id="worker", permission_manifest=manifest, discovery_policy_permission="match.discover",
            policy_context_supplier=_supplier,
        ),
    )
    worker._authorize_tenant("tenant", policy_permission="match.discover")
    with pytest.raises(PostgresReconciliationWorkerError, match="amount_missing_for_bounded_policy"):
        worker._authorize_tenant("tenant", amount=UnknownWorkerPolicyAmount.UNKNOWN)
    with pytest.raises(PostgresReconciliationWorkerError, match="amount_missing_for_bounded_policy"):
        worker.process_run(tenant_id="tenant", run_id="unknown-amount")


def test_unknown_discovered_amount_is_denied_before_claim_without_mutation() -> None:
    connection = _ReconciliationConnection()
    _create_run(PostgresReconciliationRepository(connection))
    assert connection.run is not None
    before = dict(connection.run)
    worker = PostgresReconciliationWorker(
        _ConnectionFactory(connection),
        tenant_supplier=lambda: ["tenant_a"],
        matcher=lambda _: ReconciliationExecutionResult(),
        settings=PostgresReconciliationWorkerSettings(
            worker_id="worker", permission_manifest=_worker_manifest("worker"),
            discovery_policy_permission="match.discover", policy_context_supplier=_supplier,
        ),
    )
    summary = worker.process_once()
    assert (summary.denied, summary.completed, summary.failed, summary.skipped) == (1, 0, 0, 0)
    assert connection.run == before
    assert connection.results == []
    assert connection.exceptions == []
    assert connection.checkpoints == []


def test_unknown_amount_is_denied_when_claim_policy_becomes_bounded() -> None:
    connection = _ReconciliationConnection()
    _create_run(PostgresReconciliationRepository(connection))
    assert connection.run is not None
    before = dict(connection.run)
    policy_calls = 0

    def changing_policy(tenant: str) -> PolicyEvaluationContext:
        nonlocal policy_calls
        policy_calls += 1
        return replace(_supplier(tenant), maximum_amount=None if policy_calls == 1 else Decimal("10"))

    worker = PostgresReconciliationWorker(
        _ConnectionFactory(connection),
        tenant_supplier=lambda: ["tenant_a"],
        matcher=lambda _: ReconciliationExecutionResult(),
        settings=PostgresReconciliationWorkerSettings(
            worker_id="worker", permission_manifest=_worker_manifest("worker"),
            discovery_policy_permission="match.discover", policy_context_supplier=changing_policy,
        ),
    )
    with pytest.raises(PostgresReconciliationPolicyDenied, match="amount_missing_for_bounded_policy"):
        worker.process_run(tenant_id="tenant_a", run_id="run-a", policy_amount=None)
    assert policy_calls == 2
    assert connection.run == before
    assert connection.run["execution_status"] == "Queued"
    assert connection.results == []
    assert connection.exceptions == []
    assert connection.checkpoints == []
