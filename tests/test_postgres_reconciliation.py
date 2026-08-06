"""Contract tests for hosted reconciliation result persistence and invariants."""

from __future__ import annotations

import json
import os
import re
from contextlib import contextmanager
from typing import Any
from uuid import uuid4

import pytest

from reconforge.auth.policy import PolicyEvaluationContext
from reconforge.infrastructure.postgres import (
    PostgresConnectionFactory,
    PostgresSettings,
    PostgresTenantBoundary,
    install_postgres_rls_schema,
)
from reconforge.infrastructure.postgres_ledger import POSTGRES_LEDGER_SCHEMA_SQL
from reconforge.infrastructure.postgres_master_data import POSTGRES_MASTER_DATA_SCHEMA_SQL
from reconforge.infrastructure.postgres_reconciliation import (
    POSTGRES_RECONCILIATION_SCHEMA_SQL,
    PostgresReconciliationBusyError,
    PostgresReconciliationIntegrityError,
    PostgresReconciliationNotFoundError,
    PostgresReconciliationRepository,
    PostgresReconciliationValidationError,
)
from reconforge.infrastructure.postgres_reconciliation_checkpoints import (
    POSTGRES_RECONCILIATION_CHECKPOINT_SCHEMA_SQL,
)
from reconforge.workers.postgres_reconciliation import (
    LocalDeterministicMatcherAdapter,
    PostgresReconciliationScheduler,
    PostgresReconciliationSchedulerError,
    PostgresReconciliationWorker,
    PostgresReconciliationWorkerError,
    PostgresReconciliationWorkerSettings,
    ReconciliationExecutionContext,
    ReconciliationExecutionResult,
    ReconciliationWorkerRunSummary,
)


class _Cursor:
    def __init__(self, row: Any = None, rows: list[Any] | None = None) -> None:
        self.row = row
        self.rows = rows or []
        self.position = 0

    def fetchone(self) -> Any:
        return self.row

    def fetchall(self) -> list[Any]:
        return self.rows

    def fetchmany(self, size: int = 1) -> list[Any]:
        selected = self.rows[self.position : self.position + size]
        self.position += len(selected)
        return selected


class _ReconciliationConnection:
    def __init__(self) -> None:
        self.commits = 0
        self.executed: list[tuple[str, tuple[Any, ...] | None]] = []
        self.run: dict[str, Any] | None = None
        self.inputs: list[dict[str, Any]] = []
        self.results: list[dict[str, Any]] = []
        self.exceptions: list[dict[str, Any]] = []
        self.checkpoints: list[dict[str, Any]] = []
        self.overused = 0
        self.lease_expired = False

    @contextmanager
    def transaction(self) -> Any:
        yield self
        self.commits += 1

    def close(self) -> None:
        return None

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> _Cursor:
        self.executed.append((sql, params))
        normalized = " ".join(sql.split()).lower()
        if normalized.startswith("select pg_advisory_xact_lock") or normalized.startswith("select event_hash"):
            return _Cursor()
        if normalized.startswith("insert into reconforge.audit_events") or normalized.startswith(
            "insert into reconforge.outbox_events"
        ):
            return _Cursor()
        if normalized.startswith("select tenant_id, run_id, partition_key"):
            assert params is not None
            rows = [
                item
                for item in self.checkpoints
                if item["tenant_id"] == params[0]
                and item["run_id"] == params[1]
                and (len(params) < 3 or item["partition_key"] == params[2])
            ]
            if "for update" in normalized or "partition_key = %s" in normalized:
                return _Cursor(rows[0] if rows else None)
            return _Cursor(rows=sorted(rows, key=lambda item: item["partition_key"]))
        if "from reconforge.reconciliation_runs" in normalized and "order by created_at desc" in normalized:
            return _Cursor(rows=[] if self.run is None else [self.run])
        if "from reconforge.reconciliation_runs" in normalized:
            if self.run is None:
                return _Cursor()
            return _Cursor(self.run)
        if normalized.startswith("insert into reconforge.reconciliation_runs"):
            assert params is not None
            self.run = {
                "tenant_id": params[0],
                "id": params[1],
                "name": params[2],
                "left_source": params[3],
                "right_source": params[4],
                "status": "Running",
                "algorithm_version": params[5],
                "rule_json": params[6],
                "input_hash": params[7],
                "idempotency_key": params[8],
                "created_by": params[9],
                "created_at": "2026-07-23T00:00:00Z",
                "completed_at": None,
                "left_input_count": 0,
                "right_input_count": 0,
                "result_count": 0,
                "matched_count": 0,
                "exception_count": 0,
                "input_manifest_hash": "",
                "result_set_hash": "",
                "execution_status": "Queued",
                "execution_worker_id": None,
                "execution_claimed_at": None,
                "execution_lease_until": None,
                "execution_progress": 0,
                "execution_attempt": 0,
                "execution_started_at": None,
                "execution_finished_at": None,
                "execution_error": "",
                "cancel_requested": False,
            }
            return _Cursor(self.run)
        if "missing_left" in normalized:
            missing_left = sum(
                1
                for item in self.inputs
                if item["side"] == "Left" and not any(result["left_id"] == item["source_id"] for result in self.results)
            )
            missing_right = sum(
                1
                for item in self.inputs
                if item["side"] == "Right" and not any(result["right_id"] == item["source_id"] for result in self.results)
            )
            return _Cursor((missing_left, missing_right))
        if "left_exists" in normalized:
            assert params is not None
            left_exists = sum(
                1
                for item in self.inputs
                if item["tenant_id"] == params[0]
                and item["run_id"] == params[1]
                and item["side"] == "Left"
                and item["source_id"] == params[2]
            )
            right_exists = sum(
                1
                for item in self.inputs
                if item["tenant_id"] == params[3]
                and item["run_id"] == params[4]
                and item["side"] == "Right"
                and item["source_id"] == params[5]
            )
            return _Cursor((left_exists, right_exists))
        if "partition_value_0" in normalized and "from reconforge.reconciliation_inputs" in normalized:
            rows = []
            for item in self.inputs:
                values = tuple(item[column] for column in PostgresReconciliationRepository._INPUT_COLUMNS)
                attributes = item["attributes_json"] if isinstance(item["attributes_json"], dict) else json.loads(str(item["attributes_json"]))
                rows.append(values + (attributes.get("entity_id"),))
            rows.sort(key=lambda row: (row[-1] is not None, row[-1], row[2], row[3]))
            return _Cursor(rows=rows)
        if normalized.startswith("select (select count(*)"):
            left = sum(1 for item in self.inputs if item["side"] == "Left")
            right = sum(1 for item in self.inputs if item["side"] == "Right")
            matched = sum(1 for item in self.results if item["status"] == "Matched")
            return _Cursor((left, right, len(self.results), matched, len(self.exceptions)))
        if "having count(*) > max" in normalized:
            return _Cursor((self.overused,))
        if normalized.startswith("update reconforge.reconciliation_runs") and "set execution_status = 'running'" in normalized:
            assert self.run is not None and params is not None
            assert "execution_status = 'queued'" in normalized
            assert "execution_lease_until <= now()" in normalized
            if self.run.get("execution_status") == "Running" and not self.lease_expired:
                return _Cursor()
            self.run.update(
                {
                    "execution_status": "Running",
                    "execution_worker_id": params[0],
                    "execution_claimed_at": "2026-07-23T00:01:00Z",
                    "execution_lease_until": "2026-07-23T00:06:00Z",
                    "execution_attempt": int(self.run.get("execution_attempt", 0)) + 1,
                    "execution_progress": 0,
                }
            )
            self.lease_expired = False
            return _Cursor(self.run)
        if normalized.startswith("update reconforge.reconciliation_runs") and "set execution_progress" in normalized:
            assert self.run is not None and params is not None
            self.run.update({"execution_progress": params[0]})
            return _Cursor(self.run)
        if normalized.startswith("update reconforge.reconciliation_runs") and "set cancel_requested = true" in normalized:
            assert self.run is not None
            self.run["cancel_requested"] = True
            return _Cursor(self.run)
        if normalized.startswith("update reconforge.reconciliation_runs") and "set execution_status = 'cancelled'" in normalized:
            assert self.run is not None
            self.run.update({"execution_status": "Cancelled", "execution_worker_id": None, "execution_progress": 0})
            return _Cursor(self.run)
        if normalized.startswith("update reconforge.reconciliation_runs") and "set execution_status = 'failed'" in normalized:
            assert self.run is not None and params is not None
            self.run.update({"execution_status": "Failed", "execution_worker_id": None, "execution_error": params[0]})
            return _Cursor(self.run)
        if normalized.startswith("update reconforge.reconciliation_runs") and "set execution_status = 'queued'" in normalized:
            assert self.run is not None
            self.run.update({"execution_status": "Queued", "execution_worker_id": None, "execution_progress": 0, "execution_error": "", "cancel_requested": False})
            return _Cursor(self.run)
        if normalized.startswith("update reconforge.reconciliation_runs"):
            assert self.run is not None and params is not None
            self.run.update(
                {
                    "status": "Complete",
                    "execution_status": "Complete",
                    "execution_progress": 100,
                    "execution_worker_id": None,
                    "completed_at": "2026-07-23T00:04:00Z",
                    "left_input_count": params[0],
                    "right_input_count": params[1],
                    "result_count": params[2],
                    "matched_count": params[3],
                    "exception_count": params[4],
                    "input_manifest_hash": params[5],
                    "result_set_hash": params[6],
                }
            )
            return _Cursor(self.run)
        if normalized.startswith("select tenant_id, run_id, side"):
            assert params is not None
            rows = [
                item
                for item in self.inputs
                if item["tenant_id"] == params[0] and item["run_id"] == params[1]
            ]
            return _Cursor(rows=sorted(rows, key=lambda item: (item["side"], item["source_id"])))
        if normalized.startswith("insert into reconforge.reconciliation_inputs"):
            assert params is not None
            item = {
                "tenant_id": params[0],
                "run_id": params[1],
                "side": params[2],
                "source_id": params[3],
                "record_hash": params[4],
                "amount_decimal": params[5],
                "amount_original": params[6],
                "currency_code": params[7],
                "date_original": params[8],
                "date_value": params[9],
                "reference_original": params[10],
                "reference_normalized": params[11],
                "attributes_json": params[12],
                "valid": params[13],
                "allowed_uses": params[14],
                "created_at": "2026-07-23T00:00:00Z",
            }
            if any(
                existing["tenant_id"] == item["tenant_id"]
                and existing["run_id"] == item["run_id"]
                and existing["side"] == item["side"]
                and existing["source_id"] == item["source_id"]
                for existing in self.inputs
            ):
                return _Cursor()
            self.inputs.append(item)
            return _Cursor(item)
        if normalized.startswith("select tenant_id, run_id, side, source_id"):
            assert params is not None
            for item in self.inputs:
                if item["tenant_id"] == params[0] and item["run_id"] == params[1] and item["side"] == params[2] and item["source_id"] == params[3]:
                    return _Cursor(item)
            return _Cursor()
        if normalized.startswith("select tenant_id, id, run_id, left_id") and "from reconforge.reconciliation_results" in normalized:
            assert params is not None
            rows = [item for item in self.results if item["tenant_id"] == params[0] and item["run_id"] == params[1]]
            return _Cursor(rows=sorted(rows, key=lambda item: (item["left_id"], item["right_id"], item["match_type"], item["id"])))
        if normalized.startswith("insert into reconforge.reconciliation_results"):
            assert params is not None
            item = {
                "tenant_id": params[0],
                "id": params[1],
                "run_id": params[2],
                "left_id": params[3],
                "right_id": params[4],
                "match_type": params[5],
                "confidence": params[6],
                "explanation": params[7],
                "amount_difference": params[8],
                "date_difference_days": params[9],
                "status": params[10],
                "reason_code": params[11],
                "lineage_json": params[12],
                "created_at": "2026-07-23T00:01:00Z",
            }
            if any(existing["tenant_id"] == item["tenant_id"] and existing["id"] == item["id"] for existing in self.results):
                return _Cursor()
            self.results.append(item)
            return _Cursor(item)
        if normalized.startswith("insert into reconforge.reconciliation_execution_checkpoints"):
            assert params is not None
            item = {
                "tenant_id": params[0],
                "run_id": params[1],
                "partition_key": params[2],
                "status": "Complete",
                "input_count": params[3],
                "result_count": params[4],
                "exception_count": params[5],
                "output_hash": params[6],
                "worker_id": params[7],
                "created_at": "2026-07-23T00:03:00Z",
                "completed_at": "2026-07-23T00:03:00Z",
            }
            existing = next(
                (
                    checkpoint
                    for checkpoint in self.checkpoints
                    if checkpoint["tenant_id"] == item["tenant_id"]
                    and checkpoint["run_id"] == item["run_id"]
                    and checkpoint["partition_key"] == item["partition_key"]
                ),
                None,
            )
            if existing is not None:
                return _Cursor()
            self.checkpoints.append(item)
            return _Cursor(item)
        if normalized.startswith("select tenant_id, id, run_id, left_id") and "where tenant_id = %s and id = %s" in normalized:
            assert params is not None
            return _Cursor(next((item for item in self.results if item["tenant_id"] == params[0] and item["id"] == params[1]), None))
        if normalized.startswith("select tenant_id, id, run_id, exception_type"):
            assert params is not None
            rows = [item for item in self.exceptions if item["tenant_id"] == params[0] and item["run_id"] == params[1]]
            return _Cursor(rows=rows)
        if normalized.startswith("insert into reconforge.reconciliation_exceptions"):
            assert params is not None
            item = {
                "tenant_id": params[0],
                "id": params[1],
                "run_id": params[2],
                "exception_type": params[3],
                "source_side": params[4],
                "source_id": params[5],
                "title": params[6],
                "explanation": params[7],
                "severity": params[8],
                "risk_score": params[9],
                "workflow_status": "Open",
                "owner_id": params[10],
                "reason_code": params[11],
                "evidence_json": params[12],
                "created_at": "2026-07-23T00:02:00Z",
                "updated_at": "2026-07-23T00:02:00Z",
            }
            self.exceptions.append(item)
            return _Cursor(item)
        return _Cursor()


def _create_run(repository: PostgresReconciliationRepository) -> dict[str, Any]:
    return repository.create_run(
        tenant_id="tenant_a",
        run_id="run-a",
        name="Bank to GL",
        left_source="bank.csv",
        right_source="gl.csv",
        algorithm_version="global-assignment-v1",
        rule={"amount_tolerance": "0.01", "date_window_days": 2},
        input_hash="input-manifest-a",
        actor_id="user-a",
        idempotency_key="request-a",
    )


def test_postgres_reconciliation_run_listing_is_stable_and_bounded() -> None:
    connection = _ReconciliationConnection()
    repository = PostgresReconciliationRepository(connection)
    _create_run(repository)

    runs = repository.list_runs(tenant_id="tenant_a", limit=1, offset=0)

    assert len(runs) == 1
    assert runs[0]["id"] == "run-a"
    with pytest.raises(PostgresReconciliationValidationError, match="between 1 and 1000"):
        repository.list_runs(tenant_id="tenant_a", limit=1_001)
    with pytest.raises(PostgresReconciliationValidationError, match="must be one of"):
        repository.list_runs(tenant_id="tenant_a", status="unknown")


class _ConnectionFactory:
    def __init__(self, connection: _ReconciliationConnection) -> None:
        self.connection = connection

    def connect(self) -> _ReconciliationConnection:
        return self.connection


def test_postgres_reconciliation_execution_worker_claims_persists_and_completes() -> None:
    connection = _ReconciliationConnection()
    repository = PostgresReconciliationRepository(connection)
    _create_run(repository)
    repository.register_input(
        tenant_id="tenant_a",
        run_id="run-a",
        side="Left",
        source_id="left-1",
        record_hash="hash-left-1",
        amount="100.00",
        currency_code="USD",
        attributes={"id": "left-1", "amount": "100.00", "date": "2026-07-23", "reference": "INV-001"},
    )
    repository.register_input(
        tenant_id="tenant_a",
        run_id="run-a",
        side="Right",
        source_id="right-1",
        record_hash="hash-right-1",
        amount="100.00",
        currency_code="USD",
        attributes={"id": "right-1", "amount": "100.00", "date": "2026-07-23", "reference": "INV-001"},
    )

    adapter = LocalDeterministicMatcherAdapter()

    def matcher(context: Any) -> ReconciliationExecutionResult:
        assert len(context.left_inputs) == 1
        assert len(context.right_inputs) == 1
        context.heartbeat(40)
        context.raise_if_cancelled()
        return adapter(context)

    worker = PostgresReconciliationWorker(
        _ConnectionFactory(connection),
        tenant_supplier=lambda: ["tenant_a"],
        matcher=matcher,
        settings=PostgresReconciliationWorkerSettings(worker_id="recon-worker-a", poll_interval_seconds=0),
    )

    summary = worker.process_once()

    assert summary.cycles == 1
    assert summary.discovered == 1
    assert summary.completed == 1
    assert summary.failed == 0
    assert connection.run is not None
    assert connection.run["execution_status"] == "Complete"
    assert connection.run["execution_attempt"] == 1
    assert len(connection.results) == 1
    adapter.close()


def test_postgres_reconciliation_worker_policy_denies_before_connection_access() -> None:
    class _NeverConnect:
        def connect(self) -> Any:
            raise AssertionError("policy denial must precede connection access")

    worker = PostgresReconciliationWorker(
        _NeverConnect(),
        tenant_supplier=lambda: ["tenant_a"],
        matcher=lambda _context: ReconciliationExecutionResult(),
        settings=PostgresReconciliationWorkerSettings(
            worker_id="policy-worker",
            policy_context_supplier=lambda tenant: PolicyEvaluationContext(
                user_id="policy-worker",
                username="policy-worker",
                user_permissions=set(),
                principal_type="service_account",
                tenant_id=tenant,
                authorized_tenant_ids=frozenset({tenant}),
            ),
        ),
    )
    with pytest.raises(PostgresReconciliationWorkerError, match="permission_missing"):
        worker.process_once()


def test_postgres_reconciliation_worker_policy_allows_scoped_service_identity() -> None:
    connection = _ReconciliationConnection()
    repository = PostgresReconciliationRepository(connection)
    _create_run(repository)

    worker = PostgresReconciliationWorker(
        _ConnectionFactory(connection),
        tenant_supplier=lambda: ["tenant_a"],
        matcher=lambda _context: ReconciliationExecutionResult(),
        settings=PostgresReconciliationWorkerSettings(
            worker_id="policy-worker",
            policy_context_supplier=lambda tenant: PolicyEvaluationContext(
                user_id="policy-worker",
                username="policy-worker",
                user_permissions={"match.run"},
                principal_type="service_account",
                tenant_id=tenant,
                authorized_tenant_ids=frozenset({tenant}),
            ),
        ),
    )
    summary = worker.process_once()
    assert summary.completed == 1
    assert connection.run is not None and connection.run["execution_status"] == "Complete"


def test_postgres_reconciliation_worker_propagates_workspace_scope_to_policy_and_transactions() -> None:
    connection = _ReconciliationConnection()
    repository = PostgresReconciliationRepository(connection)
    _create_run(repository)
    assert connection.run is not None
    connection.run["workspace_id"] = "workspace-a"
    policy_scopes: list[tuple[str, str | None, str | None]] = []

    def policy_context(tenant: str, workspace: str | None, entity: str | None) -> PolicyEvaluationContext:
        policy_scopes.append((tenant, workspace, entity))
        return PolicyEvaluationContext(
            user_id="scoped-worker",
            username="scoped-worker",
            user_permissions={"match.run"},
            principal_type="service_account",
            tenant_id=tenant,
            workspace_id=workspace,
            entity_id=entity,
            authorized_tenant_ids=frozenset({tenant}),
            authorized_workspace_ids=frozenset({workspace}) if workspace else frozenset(),
        )

    worker = PostgresReconciliationWorker(
        _ConnectionFactory(connection),
        tenant_supplier=lambda: ["tenant_a"],
        matcher=lambda _context: ReconciliationExecutionResult(),
        settings=PostgresReconciliationWorkerSettings(
            worker_id="scoped-worker",
            policy_context_scope_supplier=policy_context,
            poll_interval_seconds=0,
        ),
    )

    summary = worker.process_once()

    assert summary.completed == 1
    assert ("tenant_a", "workspace-a", None) in policy_scopes
    workspace_settings = [
        params
        for sql, params in connection.executed
        if "set_config('app.workspace_id'" in sql
    ]
    assert workspace_settings
    assert any(params == ("workspace-a",) for params in workspace_settings)


def test_postgres_reconciliation_worker_rejects_legacy_policy_for_scoped_run() -> None:
    connection = _ReconciliationConnection()
    repository = PostgresReconciliationRepository(connection)
    _create_run(repository)
    assert connection.run is not None
    connection.run["workspace_id"] = "workspace-a"

    worker = PostgresReconciliationWorker(
        _ConnectionFactory(connection),
        tenant_supplier=lambda: ["tenant_a"],
        matcher=lambda _context: ReconciliationExecutionResult(),
        settings=PostgresReconciliationWorkerSettings(
            worker_id="legacy-worker",
            policy_context_supplier=lambda tenant: PolicyEvaluationContext(
                user_id="legacy-worker",
                username="legacy-worker",
                user_permissions={"match.run"},
                principal_type="service_account",
                tenant_id=tenant,
                authorized_tenant_ids=frozenset({tenant}),
            ),
        ),
    )

    with pytest.raises(PostgresReconciliationWorkerError, match="scope-aware worker policy supplier"):
        worker.process_once()
    assert connection.run["execution_status"] == "Queued"


def test_local_matcher_partitioning_is_deterministic_and_reports_progress() -> None:
    adapter = LocalDeterministicMatcherAdapter()
    progress: list[int] = []
    left = [
        {
            "side": "Left",
            "source_id": "left-b",
            "amount_decimal": "20.00",
            "attributes_json": {"id": "left-b", "amount": "20.00", "date": "2026-07-23", "reference": "INV-B", "entity_id": "B"},
        },
        {
            "side": "Left",
            "source_id": "left-a",
            "amount_decimal": "10.00",
            "attributes_json": {"id": "left-a", "amount": "10.00", "date": "2026-07-23", "reference": "INV-A", "entity_id": "A"},
        },
    ]
    right = [
        {
            "side": "Right",
            "source_id": "right-a",
            "amount_decimal": "10.00",
            "attributes_json": {"id": "right-a", "amount": "10.00", "date": "2026-07-23", "reference": "INV-A", "entity_id": "A"},
        },
        {
            "side": "Right",
            "source_id": "right-b",
            "amount_decimal": "20.00",
            "attributes_json": {"id": "right-b", "amount": "20.00", "date": "2026-07-23", "reference": "INV-B", "entity_id": "B"},
        },
    ]

    def execute(left_records: list[dict[str, Any]], right_records: list[dict[str, Any]]) -> ReconciliationExecutionResult:
        context = ReconciliationExecutionContext(
            run={"rule_json": {"partition_fields": ["entity_id"], "amount_tolerance": "0"}},
            left_inputs=tuple(left_records),
            right_inputs=tuple(right_records),
            heartbeat=lambda value: progress.append(value) or {},
            cancellation_requested=lambda: False,
        )
        return adapter(context)

    first = execute(left, right)
    second = execute(list(reversed(left)), list(reversed(right)))
    assert sorted(first.results, key=lambda item: str(item)) == sorted(second.results, key=lambda item: str(item))
    assert first.exceptions == second.exceptions == ()
    assert all(record["lineage"]["partition_fields"] == ["entity_id"] for record in first.results)
    assert progress and max(progress) == 95
    adapter.close()


def test_local_matcher_uses_persisted_financial_input_policy() -> None:
    adapter = LocalDeterministicMatcherAdapter()
    left = (
        {
            "side": "Left",
            "source_id": "left-1",
            "amount_decimal": "10.50",
            "attributes_json": {
                "id": "left-1",
                "amount": 10.5,
                "date": "2026-07-25",
                "reference": "INV-1",
            },
        },
    )
    right = (
        {
            "side": "Right",
            "source_id": "right-1",
            "amount_decimal": "10.50",
            "attributes_json": {
                "id": "right-1",
                "amount": 10.5,
                "date": "2026-07-25",
                "reference": "INV-1",
            },
        },
    )

    def execute(policy: str | None, identity_policy: str | None = None) -> ReconciliationExecutionResult:
        rule = {"amount_tolerance": "0"}
        if policy is not None:
            rule["financial_input_policy"] = policy
        if identity_policy is not None:
            rule["record_identity_policy"] = identity_policy
        return adapter(
            ReconciliationExecutionContext(
                run={"rule_json": rule},
                left_inputs=left,
                right_inputs=right,
                heartbeat=lambda _: {},
                cancellation_requested=lambda: False,
            )
        )

    try:
        historical = execute(None)
        strict = execute(
            "strict-financial-input-v2",
            "canonical-multiset-occurrence-v1",
        )
    finally:
        adapter.close()

    assert sum(item["status"] == "Matched" for item in historical.results) == 1
    assert not any(item["status"] == "Matched" for item in strict.results)
    assert {item["reason_code"] for item in strict.exceptions} == {"INVALID_AMOUNT"}
    historical_lineage = historical.results[0]["lineage"]["left_record"]
    strict_lineage = strict.results[0]["lineage"]["left_record"]
    assert historical_lineage["record_identity_policy"] == "row-order-occurrence-legacy-v0"
    assert strict_lineage["record_identity_policy"] == "canonical-multiset-occurrence-v1"


def test_local_matcher_partition_limit_fails_closed() -> None:
    adapter = LocalDeterministicMatcherAdapter()
    context = ReconciliationExecutionContext(
        run={"rule_json": {"partition_fields": ["entity_id"], "partition_max_records": 1}},
        left_inputs=(
            {"source_id": "left-1", "amount_decimal": "10.00", "attributes_json": {"id": "left-1", "amount": "10.00", "entity_id": "A"}},
        ),
        right_inputs=(
            {"source_id": "right-1", "amount_decimal": "10.00", "attributes_json": {"id": "right-1", "amount": "10.00", "entity_id": "A"}},
        ),
        heartbeat=lambda _: {},
        cancellation_requested=lambda: False,
    )
    with pytest.raises(PostgresReconciliationWorkerError, match="partition_max_records"):
        adapter(context)
    adapter.close()


def test_postgres_reconciliation_partition_checkpoint_is_idempotent() -> None:
    connection = _ReconciliationConnection()
    repository = PostgresReconciliationRepository(connection)
    _create_run(repository)
    repository.register_input(
        tenant_id="tenant_a",
        run_id="run-a",
        side="Left",
        source_id="left-1",
        record_hash="hash-left-1",
        amount="10.00",
    )
    repository.register_input(
        tenant_id="tenant_a",
        run_id="run-a",
        side="Right",
        source_id="right-1",
        record_hash="hash-right-1",
        amount="10.00",
    )
    repository.claim_run(tenant_id="tenant_a", run_id="run-a", worker_id="worker-a")
    result = {
        "left_id": "left-1",
        "right_id": "right-1",
        "match_type": "deterministic",
        "confidence": "1",
        "explanation": "Exact amount",
        "amount_difference": "0",
        "status": "Matched",
        "reason_code": "EXACT",
    }

    first = repository.append_partition(
        tenant_id="tenant_a",
        run_id="run-a",
        partition_key="partition-a",
        input_count=2,
        results=[result],
        worker_id="worker-a",
    )
    second = repository.append_partition(
        tenant_id="tenant_a",
        run_id="run-a",
        partition_key="partition-a",
        input_count=2,
        results=[result],
        worker_id="worker-a",
    )

    assert first == second
    assert len(connection.results) == 1
    assert repository.list_checkpoints(tenant_id="tenant_a", run_id="run-a") == [first]
    assert "FOR UPDATE" in POSTGRES_RECONCILIATION_CHECKPOINT_SCHEMA_SQL or "PRIMARY KEY" in POSTGRES_RECONCILIATION_CHECKPOINT_SCHEMA_SQL


def _create_partitioned_reconciliation(
    connection: _ReconciliationConnection,
    *,
    run_id: str,
) -> PostgresReconciliationRepository:
    repository = PostgresReconciliationRepository(connection)
    repository.create_run(
        tenant_id="tenant_a",
        run_id=run_id,
        name="Partitioned reconciliation",
        left_source="left.csv",
        right_source="right.csv",
        algorithm_version="partitioned-v1",
        rule={"partition_fields": ["entity_id"], "partition_max_records": 10},
        input_hash="resume-input",
        actor_id="user-a",
    )
    for side, source_id, entity in (
        ("Left", "left-a", "A"),
        ("Left", "left-b", "B"),
        ("Right", "right-a", "A"),
        ("Right", "right-b", "B"),
    ):
        repository.register_input(
            tenant_id="tenant_a",
            run_id=run_id,
            side=side,
            source_id=source_id,
            record_hash=f"hash-{source_id}",
            amount="10.00",
            currency_code="USD",
            attributes={
                "id": source_id,
                "amount": "10.00",
                "date": "2026-07-23",
                "reference": f"INV-{entity}",
                "entity_id": entity,
            },
        )
    return repository


def test_postgres_reconciliation_worker_resumes_after_partition_failure() -> None:
    connection = _ReconciliationConnection()
    repository = _create_partitioned_reconciliation(connection, run_id="run-resume")

    adapter = LocalDeterministicMatcherAdapter()

    class _FailOnce:
        def __init__(self) -> None:
            self.failed = False
            self.seen: list[str] = []

        def iter_partition_results(
            self,
            context: ReconciliationExecutionContext,
            *,
            completed_partition_keys: frozenset[str] = frozenset(),
        ) -> Any:
            for partition in adapter.iter_partition_results(
                context,
                completed_partition_keys=completed_partition_keys,
            ):
                self.seen.append(partition.partition_key)
                yield partition
                if not self.failed:
                    self.failed = True
                    raise RuntimeError("synthetic failure after committed partition")

    matcher = _FailOnce()
    worker = PostgresReconciliationWorker(
        _ConnectionFactory(connection),
        tenant_supplier=lambda: ["tenant_a"],
        matcher=matcher,
        settings=PostgresReconciliationWorkerSettings(worker_id="worker-a", poll_interval_seconds=0),
    )

    failed = worker.process_run(tenant_id="tenant_a", run_id="run-resume")
    assert failed.status == "Failed"
    assert len(connection.checkpoints) == 1
    repository.requeue_run(tenant_id="tenant_a", run_id="run-resume", actor_id="operator-a")
    completed = worker.process_run(tenant_id="tenant_a", run_id="run-resume")

    assert completed.status == "Complete"
    assert len(connection.checkpoints) == 2
    assert len(connection.results) == 2
    assert len(matcher.seen) == 2
    assert connection.run is not None and connection.run["execution_status"] == "Complete"
    streamed_queries = [
        params
        for sql, params in connection.executed
        if "partition_value_0" in sql
    ]
    assert streamed_queries and streamed_queries[-1][-2:] == ("tenant_a", "run-resume")
    adapter.close()


def test_postgres_reconciliation_worker_resumes_after_unhandled_crash_and_lease_expiry() -> None:
    run_id = "run-crash-resume"
    adapter = LocalDeterministicMatcherAdapter()
    try:
        baseline_connection = _ReconciliationConnection()
        _create_partitioned_reconciliation(baseline_connection, run_id=run_id)
        baseline_worker = PostgresReconciliationWorker(
            _ConnectionFactory(baseline_connection),
            tenant_supplier=lambda: ["tenant_a"],
            matcher=adapter,
            settings=PostgresReconciliationWorkerSettings(worker_id="worker-baseline", poll_interval_seconds=0),
        )
        baseline = baseline_worker.process_run(tenant_id="tenant_a", run_id=run_id)
        assert baseline.status == "Complete"
        assert baseline_connection.run is not None

        crash_connection = _ReconciliationConnection()
        _create_partitioned_reconciliation(crash_connection, run_id=run_id)

        class _SyntheticProcessCrash(BaseException):
            pass

        class _CrashAfterFirstCheckpoint:
            def __init__(self) -> None:
                self.crashed = False
                self.seen_by_attempt: list[list[str]] = []

            def iter_partition_results(
                self,
                context: ReconciliationExecutionContext,
                *,
                completed_partition_keys: frozenset[str] = frozenset(),
            ) -> Any:
                seen: list[str] = []
                self.seen_by_attempt.append(seen)
                for partition in adapter.iter_partition_results(
                    context,
                    completed_partition_keys=completed_partition_keys,
                ):
                    seen.append(partition.partition_key)
                    yield partition
                    if not self.crashed:
                        self.crashed = True
                        raise _SyntheticProcessCrash("synthetic process termination after checkpoint commit")

        matcher = _CrashAfterFirstCheckpoint()
        first_worker = PostgresReconciliationWorker(
            _ConnectionFactory(crash_connection),
            tenant_supplier=lambda: ["tenant_a"],
            matcher=matcher,
            settings=PostgresReconciliationWorkerSettings(worker_id="worker-a", poll_interval_seconds=0),
        )
        with pytest.raises(_SyntheticProcessCrash, match="after checkpoint commit"):
            first_worker.process_run(tenant_id="tenant_a", run_id=run_id)

        assert crash_connection.run is not None
        assert crash_connection.run["execution_status"] == "Running"
        assert crash_connection.run["execution_worker_id"] == "worker-a"
        assert crash_connection.run["execution_attempt"] == 1
        assert len(crash_connection.checkpoints) == 1
        assert len(crash_connection.results) == 1

        replacement_worker = PostgresReconciliationWorker(
            _ConnectionFactory(crash_connection),
            tenant_supplier=lambda: ["tenant_a"],
            matcher=matcher,
            settings=PostgresReconciliationWorkerSettings(worker_id="worker-b", poll_interval_seconds=0),
        )
        with pytest.raises(PostgresReconciliationBusyError, match="already leased"):
            replacement_worker.process_run(tenant_id="tenant_a", run_id=run_id)
        assert len(matcher.seen_by_attempt) == 1

        crash_connection.lease_expired = True
        resumed = replacement_worker.process_run(tenant_id="tenant_a", run_id=run_id)

        assert resumed.status == "Complete"
        assert resumed.result_count == 2
        assert crash_connection.run["execution_status"] == "Complete"
        assert crash_connection.run["execution_worker_id"] is None
        assert crash_connection.run["execution_attempt"] == 2
        assert len(crash_connection.checkpoints) == 2
        assert len(crash_connection.results) == 2
        assert len({str(item["id"]) for item in crash_connection.results}) == 2
        assert len(matcher.seen_by_attempt) == 2
        assert all(len(attempt) == 1 for attempt in matcher.seen_by_attempt)
        assert set(matcher.seen_by_attempt[0]).isdisjoint(matcher.seen_by_attempt[1])
        assert [item["worker_id"] for item in crash_connection.checkpoints] == ["worker-a", "worker-b"]
        assert crash_connection.run["input_manifest_hash"] == baseline_connection.run["input_manifest_hash"]
        assert crash_connection.run["result_set_hash"] == baseline_connection.run["result_set_hash"]
        assert sorted(item["output_hash"] for item in crash_connection.checkpoints) == sorted(
            item["output_hash"] for item in baseline_connection.checkpoints
        )
    finally:
        adapter.close()


def test_postgres_reconciliation_scheduler_aggregates_worker_slots() -> None:
    created: list[str] = []

    class _Worker:
        def __init__(self, worker_id: str) -> None:
            self.worker_id = worker_id

        def process_once(self) -> ReconciliationWorkerRunSummary:
            created.append(self.worker_id)
            return ReconciliationWorkerRunSummary(cycles=1, discovered=2, completed=1, failed=0, cancelled=0, skipped=1)

    scheduler = PostgresReconciliationScheduler(_Worker, worker_ids=["worker-b", "worker-a"], poll_interval_seconds=0)
    summary = scheduler.process_once()
    assert created == ["worker-a", "worker-b"]
    assert summary == ReconciliationWorkerRunSummary(cycles=2, discovered=4, completed=2, failed=0, cancelled=0, skipped=2)
    with pytest.raises(PostgresReconciliationSchedulerError, match="between 1 and 64"):
        PostgresReconciliationScheduler(_Worker, worker_ids=[])


def test_postgres_reconciliation_execution_failure_is_retryable_and_busy_runs_are_skipped() -> None:
    connection = _ReconciliationConnection()
    repository = PostgresReconciliationRepository(connection)
    _create_run(repository)

    def matcher(_: Any) -> ReconciliationExecutionResult:
        raise RuntimeError("synthetic matcher failure")

    worker = PostgresReconciliationWorker(
        _ConnectionFactory(connection),
        tenant_supplier=lambda: ["tenant_a"],
        matcher=matcher,
        settings=PostgresReconciliationWorkerSettings(worker_id="recon-worker-a", poll_interval_seconds=0),
    )
    failed = worker.process_run(tenant_id="tenant_a", run_id="run-a")

    assert failed.status == "Failed"
    assert connection.run is not None
    assert connection.run["execution_error"] == "synthetic matcher failure"
    requeued = repository.requeue_run(tenant_id="tenant_a", run_id="run-a", actor_id="operator-a")
    assert requeued["execution_status"] == "Queued"

    claimed = repository.claim_run(tenant_id="tenant_a", run_id="run-a", worker_id="recon-worker-a")
    assert claimed["execution_status"] == "Running"
    with pytest.raises(PostgresReconciliationBusyError):
        repository.claim_run(tenant_id="tenant_a", run_id="run-a", worker_id="recon-worker-b")

    # A stale active-page result can race with a completion.  The terminal
    # status is contention, not a scheduler-fatal integrity violation.
    assert connection.run is not None
    connection.run.update({"status": "Complete", "execution_status": "Complete"})
    with pytest.raises(PostgresReconciliationBusyError):
        repository.claim_run(tenant_id="tenant_a", run_id="run-a", worker_id="recon-worker-c")


def test_postgres_reconciliation_requires_complete_left_and_right_coverage() -> None:
    connection = _ReconciliationConnection()
    repository = PostgresReconciliationRepository(connection)
    run = _create_run(repository)
    repository.register_input(
        tenant_id="tenant_a",
        run_id="run-a",
        side="Left",
        source_id="left-1",
        record_hash="hash-left-1",
        amount="100.00",
        currency_code="USD",
        date_value="2026-07-23",
        reference_original="INV-001",
        reference_normalized="INV1",
    )
    repository.register_input(
        tenant_id="tenant_a",
        run_id="run-a",
        side="Left",
        source_id="left-2",
        record_hash="hash-left-2",
        amount="25.00",
        currency_code="USD",
    )
    repository.register_input(
        tenant_id="tenant_a",
        run_id="run-a",
        side="Right",
        source_id="right-1",
        record_hash="hash-right-1",
        amount="100.00",
        currency_code="USD",
    )
    repository.register_input(
        tenant_id="tenant_a",
        run_id="run-a",
        side="Right",
        source_id="right-2",
        record_hash="hash-right-2",
        amount="25.00",
        currency_code="USD",
    )
    repository.append_result(
        tenant_id="tenant_a",
        run_id="run-a",
        left_id="left-1",
        right_id="right-1",
        match_type="deterministic",
        confidence="0.99",
        explanation="Exact reference and amount",
        amount_difference="0",
        status="Matched",
    )
    with pytest.raises(PostgresReconciliationIntegrityError, match="no result"):
        repository.complete_run(tenant_id="tenant_a", run_id="run-a", actor_id="user-a")

    repository.append_result(
        tenant_id="tenant_a",
        run_id="run-a",
        left_id="left-2",
        match_type="unmatched",
        confidence="0",
        explanation="No candidate met policy",
        status="Unmatched",
        reason_code="MISSING_RIGHT",
    )
    repository.append_result(
        tenant_id="tenant_a",
        run_id="run-a",
        right_id="right-2",
        match_type="unmatched_right",
        confidence="0",
        explanation="No left candidate met policy",
        status="Unmatched",
        reason_code="MISSING_LEFT",
    )
    repository.append_exception(
        tenant_id="tenant_a",
        run_id="run-a",
        exception_type="amount_difference",
        source_side="Left",
        source_id="left-2",
        title="Amount difference",
        explanation="No right record was selected.",
        severity="High",
        risk_score="0.75",
        reason_code="MISSING_RIGHT",
    )
    completed = repository.complete_run(tenant_id="tenant_a", run_id="run-a", actor_id="user-a")

    assert run["status"] == "Running"
    assert completed["status"] == "Complete"
    assert completed["left_input_count"] == 2
    assert completed["right_input_count"] == 2
    assert completed["result_count"] == 3
    assert completed["matched_count"] == 1
    assert completed["exception_count"] == 1
    assert completed["input_manifest_hash"]
    assert completed["result_set_hash"]
    assert connection.commits == 0
    assert any(params is not None and "tenant_a" in params for _, params in connection.executed)


def test_postgres_reconciliation_rejects_float_money_and_overuse() -> None:
    connection = _ReconciliationConnection()
    repository = PostgresReconciliationRepository(connection)
    _create_run(repository)
    with pytest.raises(PostgresReconciliationValidationError, match="binary float"):
        repository.register_input(
            tenant_id="tenant_a",
            run_id="run-a",
            side="Left",
            source_id="left-1",
            record_hash="hash-left-1",
            amount=1.2,
        )
    with pytest.raises(PostgresReconciliationValidationError, match="between 0 and 1"):
        repository.append_result(
            tenant_id="tenant_a",
            run_id="run-a",
            left_id="left-1",
            match_type="deterministic",
            confidence="1.1",
            explanation="invalid confidence",
            status="Matched",
        )
    connection.overused = 1
    with pytest.raises(PostgresReconciliationIntegrityError, match="allowed use count"):
        repository.complete_run(tenant_id="tenant_a", run_id="run-a", actor_id="user-a")


def test_postgres_reconciliation_schema_has_exact_money_rls_and_immutability_guards() -> None:
    assert "NUMERIC(38,18)" in POSTGRES_RECONCILIATION_SCHEMA_SQL
    assert "FORCE ROW LEVEL SECURITY" in POSTGRES_RECONCILIATION_SCHEMA_SQL
    assert "reconciliation_results_immutable" in POSTGRES_RECONCILIATION_SCHEMA_SQL
    assert "reconciliation_runs_no_delete" in POSTGRES_RECONCILIATION_SCHEMA_SQL
    assert "input_manifest_hash" in POSTGRES_RECONCILIATION_SCHEMA_SQL
    assert "execution_status" in POSTGRES_RECONCILIATION_SCHEMA_SQL
    assert "execution_lease_until" in POSTGRES_RECONCILIATION_SCHEMA_SQL
    assert "cancel_requested" in POSTGRES_RECONCILIATION_SCHEMA_SQL


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires a live PostgreSQL service")
def test_live_postgres_reconciliation_persists_complete_runs_under_rls() -> None:
    pytest.importorskip("psycopg")
    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if not app_user:
        pytest.skip("live reconciliation test requires a non-privileged application role")
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", app_user):
        pytest.fail("RECONFORGE_TEST_POSTGRES_APP_USER contains unsafe characters")
    factory = PostgresConnectionFactory(PostgresSettings(dsn=dsn, require_tls=False))
    admin_factory = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False))
    tenant_a = "reconciliation_live_a"
    tenant_b = "reconciliation_live_b"
    run_id = "run-live-" + uuid4().hex[:16]
    admin = admin_factory.connect()
    try:
        with admin.transaction():
            install_postgres_rls_schema(admin)
            admin.execute(POSTGRES_MASTER_DATA_SCHEMA_SQL)
            admin.execute(POSTGRES_LEDGER_SCHEMA_SQL)
            admin.execute(POSTGRES_RECONCILIATION_SCHEMA_SQL)
            admin.execute(POSTGRES_RECONCILIATION_CHECKPOINT_SCHEMA_SQL)
            admin.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
            admin.execute(
                f"GRANT SELECT, INSERT, UPDATE, DELETE ON reconforge.tenants, reconforge.audit_events, "
                f"reconforge.outbox_events, reconforge.reconciliation_runs, reconforge.reconciliation_inputs, "
                f"reconforge.reconciliation_results, reconforge.reconciliation_exceptions, "
                f"reconforge.reconciliation_execution_checkpoints TO {app_user}"
            )
            admin.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA reconforge TO {app_user}")
            for tenant in (tenant_a, tenant_b):
                admin.execute(
                    "INSERT INTO reconforge.tenants (id, name) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING",
                    (tenant, tenant),
                )
        connection = factory.connect()
        try:
            role = connection.execute(
                "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
            ).fetchone()
        finally:
            connection.close()
        if role is None or bool(role[0]) or bool(role[1]):
            pytest.skip("live reconciliation test requires a non-superuser, non-BYPASSRLS application role")
        with PostgresTenantBoundary(factory).transaction(tenant_a) as connection:
            repository = PostgresReconciliationRepository(connection)
            repository.create_run(
                tenant_id=tenant_a,
                run_id=run_id,
                name="Live reconciliation",
                left_source="left.csv",
                right_source="right.csv",
                algorithm_version="global-assignment-v1",
                rule={"amount_tolerance": "0"},
                input_hash=uuid4().hex,
                actor_id="live-user",
            )
            repository.register_input(
                tenant_id=tenant_a,
                run_id=run_id,
                side="Left",
                source_id="left-live",
                record_hash=uuid4().hex,
                amount="10.00",
                currency_code="USD",
            )
            repository.register_input(
                tenant_id=tenant_a,
                run_id=run_id,
                side="Right",
                source_id="right-live",
                record_hash=uuid4().hex,
                amount="10.00",
                currency_code="USD",
            )
            streamed = list(
                repository.iter_input_partitions(
                    tenant_id=tenant_a,
                    run_id=run_id,
                    partition_fields=("source_id",),
                    batch_size=1,
                )
            )
            assert len(streamed) == 2
            assert all(len(left) + len(right) == 1 for _, left, right in streamed)
            repository.append_result(
                tenant_id=tenant_a,
                run_id=run_id,
                left_id="left-live",
                right_id="right-live",
                match_type="deterministic",
                confidence="1",
                explanation="Exact synthetic live contract match",
                status="Matched",
            )
            claimed = repository.claim_run(
                tenant_id=tenant_a,
                run_id=run_id,
                worker_id="live-reconciliation-worker",
            )
            assert claimed["execution_status"] == "Running"
            heartbeat = repository.heartbeat_run(
                tenant_id=tenant_a,
                run_id=run_id,
                worker_id="live-reconciliation-worker",
                progress=50,
            )
            assert heartbeat["execution_progress"] == 50
            completed = repository.complete_run(
                tenant_id=tenant_a,
                run_id=run_id,
                actor_id="live-user",
                worker_id="live-reconciliation-worker",
            )
            assert completed["status"] == "Complete"
            assert completed["execution_status"] == "Complete"
            assert completed["result_count"] == 1
        with PostgresTenantBoundary(factory).transaction(tenant_b) as connection, pytest.raises(PostgresReconciliationNotFoundError):
            PostgresReconciliationRepository(connection).get_run(tenant_id=tenant_b, run_id=run_id)
    finally:
        admin.close()
