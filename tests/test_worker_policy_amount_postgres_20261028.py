"""Restricted-role PostgreSQL proof for reconciliation worker amount policy."""

from __future__ import annotations

import os
from dataclasses import replace
from decimal import Decimal
from uuid import uuid4

import pytest

from reconforge.auth.policy import PolicyEvaluationContext
from reconforge.deployment import WorkerPermissionManifest
from reconforge.infrastructure.postgres import PostgresConnectionFactory, PostgresSettings, PostgresTenantBoundary
from reconforge.infrastructure.postgres_reconciliation import PostgresReconciliationRepository
from reconforge.workers.postgres_reconciliation import (
    PostgresReconciliationPolicyDenied,
    PostgresReconciliationWorker,
    PostgresReconciliationWorkerError,
    PostgresReconciliationWorkerSettings,
    ReconciliationExecutionResult,
)

pytestmark = pytest.mark.skipif(
    not os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN") or not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"),
    reason="Requires owned migrated PostgreSQL; AMR-RECONCILIATION-EXPOSURE-20261028; review 2026-11-28",
)


@pytest.fixture
def worker_database():
    import psycopg

    tenant = "worker-amount-" + uuid4().hex[:12]
    with psycopg.connect(os.environ["RECONFORGE_TEST_POSTGRES_ADMIN_DSN"]) as conn:
        conn.execute("INSERT INTO reconforge.tenants(id,name) VALUES (%s,%s)", (tenant, "Synthetic worker tenant"))
    factory = PostgresConnectionFactory(PostgresSettings(dsn=os.environ["RECONFORGE_TEST_POSTGRES_DSN"], require_tls=False))
    with PostgresTenantBoundary(factory).transaction(tenant) as conn:
        role = conn.execute("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()
        flags = conn.execute(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
            "WHERE oid='reconforge.reconciliation_runs'::regclass"
        ).fetchone()
        assert tuple(role) == (False, False)
        assert tuple(flags) == (True, True)
    return tenant, factory


def _create_run(tenant: str, factory: PostgresConnectionFactory, run_id: str, amount: str | None) -> None:
    with PostgresTenantBoundary(factory).transaction(tenant) as conn:
        repo = PostgresReconciliationRepository(conn)
        repo.create_run(
            tenant_id=tenant, run_id=run_id, name="Synthetic exposure", left_source="left.csv",
            right_source="right.csv", algorithm_version="deterministic-global-v1",
            rule={"policy_amount": amount}, input_hash="synthetic-input", actor_id="synthetic-actor",
        )
        input_amount = {"10.00": "5.00", "11.00": "5.50"}.get(amount, "1.00")
        for side in ("Left", "Right"):
            repo.register_input(
                tenant_id=tenant, run_id=run_id, side=side, source_id=side,
                record_hash="hash-" + side, amount=input_amount, currency_code="USD",
                attributes={"date": "2026-10-28", "currency": "USD"},
            )


def _snapshot(tenant: str, factory: PostgresConnectionFactory, run_id: str) -> tuple[object, ...]:
    with PostgresTenantBoundary(factory).transaction(tenant) as conn:
        repo = PostgresReconciliationRepository(conn)
        return (
            repo.get_run_metadata(tenant_id=tenant, run_id=run_id),
            repo.list_inputs(tenant_id=tenant, run_id=run_id),
            repo.list_results(tenant_id=tenant, run_id=run_id),
            repo.list_exceptions(tenant_id=tenant, run_id=run_id),
            repo.list_checkpoints(tenant_id=tenant, run_id=run_id),
        )


def _context(tenant: str) -> PolicyEvaluationContext:
    return PolicyEvaluationContext(
        user_id="worker", username="worker", user_permissions={"match.discover", "match.run"},
        principal_type="service_account", tenant_id=tenant, authorized_tenant_ids=frozenset({tenant}),
        amount=Decimal("1"), maximum_amount=Decimal("10"),
    )


def _worker(tenant: str, factory: PostgresConnectionFactory, supplier) -> PostgresReconciliationWorker:
    manifest = WorkerPermissionManifest(
        worker_id="worker", principal_id="worker", discovery_permission="match.discover",
        execution_permission="match.run", granted_permissions=("match.discover", "match.run"),
        scope="tenant:" + tenant,
    )
    return PostgresReconciliationWorker(
        factory, tenant_supplier=lambda: [tenant], matcher=lambda _: ReconciliationExecutionResult(results=({
            "left_id": "Left", "right_id": "Right", "match_type": "deterministic", "confidence": "1",
            "explanation": "Synthetic exact match", "amount_difference": "0", "status": "Matched",
        },)),
        settings=PostgresReconciliationWorkerSettings(
            worker_id="worker", permission_manifest=manifest, discovery_policy_permission="match.discover",
            policy_context_supplier=supplier, poll_interval_seconds=0,
        ),
    )


def test_unknown_discovered_exposure_is_rejected_before_claim_without_changes(worker_database) -> None:
    tenant, factory = worker_database
    _create_run(tenant, factory, "unknown", None)
    before = _snapshot(tenant, factory, "unknown")
    with pytest.raises(PostgresReconciliationWorkerError, match="amount_missing_for_bounded_policy"):
        _worker(tenant, factory, _context).process_once()
    assert _snapshot(tenant, factory, "unknown") == before


def test_unknown_exposure_is_rechecked_inside_transaction_before_claim(worker_database) -> None:
    tenant, factory = worker_database
    _create_run(tenant, factory, "recheck", None)
    before = _snapshot(tenant, factory, "recheck")
    calls = 0

    def changed_policy(scope: str) -> PolicyEvaluationContext:
        nonlocal calls
        calls += 1
        return replace(_context(scope), maximum_amount=None if calls == 1 else Decimal("10"))

    with pytest.raises(PostgresReconciliationPolicyDenied, match="amount_missing_for_bounded_policy"):
        _worker(tenant, factory, changed_policy).process_run(tenant_id=tenant, run_id="recheck")
    assert calls == 2
    assert _snapshot(tenant, factory, "recheck") == before


def test_known_exposure_allowed_and_above_limit_rejected(worker_database) -> None:
    tenant, factory = worker_database
    _create_run(tenant, factory, "allowed", "10.00")
    _create_run(tenant, factory, "denied", "11.00")
    worker = _worker(tenant, factory, _context)
    before = _snapshot(tenant, factory, "denied")
    with pytest.raises(PostgresReconciliationWorkerError, match="amount_above_ceiling"):
        worker.process_run(tenant_id=tenant, run_id="denied", policy_amount=Decimal("11.00"))
    assert _snapshot(tenant, factory, "denied") == before
    outcome = worker.process_run(tenant_id=tenant, run_id="allowed", policy_amount=Decimal("10.00"))
    after = _snapshot(tenant, factory, "allowed")
    assert outcome.status == "Complete", after[0].get("execution_error")


def test_process_once_passes_stored_known_amount_and_completes(worker_database, monkeypatch) -> None:
    from reconforge.workers import postgres_reconciliation as worker_module

    tenant, factory = worker_database
    _create_run(tenant, factory, "discovered-allowed", "10.00")
    amounts = []
    guard = worker_module.require_service_worker_policy

    def observe_guard(**kwargs):
        amounts.append(kwargs.get("amount"))
        return guard(**kwargs)

    monkeypatch.setattr(worker_module, "require_service_worker_policy", observe_guard)
    summary = _worker(tenant, factory, _context).process_once()
    assert (summary.discovered, summary.completed) == (1, 1)
    assert amounts == [None, Decimal("10.00"), Decimal("10.00")]
    assert _snapshot(tenant, factory, "discovered-allowed")[0]["execution_status"] == "Complete"


def test_process_once_rejects_stored_above_limit_before_claim(worker_database) -> None:
    tenant, factory = worker_database
    _create_run(tenant, factory, "discovered-denied", "11.00")
    before = _snapshot(tenant, factory, "discovered-denied")
    with pytest.raises(PostgresReconciliationWorkerError, match="amount_above_ceiling"):
        _worker(tenant, factory, _context).process_once()
    assert _snapshot(tenant, factory, "discovered-denied") == before
