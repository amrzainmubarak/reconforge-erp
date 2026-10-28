"""Native regressions for result identity collisions and atomic partition writes."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier
from typing import Any

import pytest

from reconforge.infrastructure.postgres import PostgresTenantBoundary, set_local_tenant_scope
from reconforge.infrastructure.postgres_reconciliation import (
    PostgresReconciliationIntegrityError,
    PostgresReconciliationRepository,
    PostgresReconciliationValidationError,
)
from tests.test_reconciliation_exception_collision import (
    TENANT,
    owned_collision_database,  # noqa: F401 -- pytest fixture
    run_repository,  # noqa: F401 -- pytest fixture
)


def _item(**overrides: object) -> dict[str, Any]:
    return {
        "left_id": "Left", "right_id": "Right", "match_type": "deterministic", "confidence": "0.9",
        "explanation": "Synthetic result", "amount_difference": "0", "date_difference_days": 0,
        "status": "Matched", "reason_code": "MATCH", "lineage": {"source": "original", "flag": True},
        **overrides,
    }


def _state(boundary: PostgresTenantBoundary, run_id: str):
    with boundary.transaction(TENANT) as connection:
        repo = PostgresReconciliationRepository(connection)
        return repo.list_results(tenant_id=TENANT, run_id=run_id), repo.list_checkpoints(tenant_id=TENANT, run_id=run_id)


def _distinct() -> dict[str, Any]:
    return _item(right_id="", match_type="unmatched", status="Unmatched", reason_code="MISSING_RIGHT")


def test_empty_result_batch_does_not_access_database() -> None:
    class NoDatabaseAccess:
        def execute(self, *_: object) -> object:
            raise AssertionError("empty result batch must not access the database")

    repository = PostgresReconciliationRepository(NoDatabaseAccess())
    assert repository.append_results_batch(tenant_id="", run_id="", items=[], chunk_size=0) == []
    assert repository.append_exceptions_batch(tenant_id="", run_id="", items=[], chunk_size=False) == []


@pytest.mark.parametrize("method", ["append_results_batch", "append_exceptions_batch"])
@pytest.mark.parametrize("chunk_size", [-1, 0, True, False, 5001, 1.0, None, "1"])
def test_nonempty_batch_rejects_invalid_chunk_size_before_any_sql(method: str, chunk_size: object) -> None:
    class NoDatabaseAccess:
        def execute(self, *_: object) -> object:
            raise AssertionError("invalid chunk size must not access database")

    repository = PostgresReconciliationRepository(NoDatabaseAccess())
    with pytest.raises(PostgresReconciliationValidationError, match="chunk_size"):
        getattr(repository, method)(tenant_id="tenant", run_id="run", items=[{}], chunk_size=chunk_size)


@pytest.mark.parametrize("method", ["append_results_batch", "append_exceptions_batch"])
@pytest.mark.parametrize("chunk_size", [1, 5000])
def test_valid_chunk_size_reaches_transaction_without_validation_error(method: str, chunk_size: int) -> None:
    class ReachedDatabase(Exception):
        pass

    class StopAtDatabase:
        def execute(self, *_: object) -> object:
            raise ReachedDatabase

    repository = PostgresReconciliationRepository(StopAtDatabase())
    with pytest.raises(ReachedDatabase):
        getattr(repository, method)(tenant_id="tenant", run_id="run", items=[{}], chunk_size=chunk_size)


@pytest.mark.parametrize("changes", [
    {"confidence": "0.8"}, {"explanation": "Changed"}, {"amount_difference": "4"},
    {"date_difference_days": 1}, {"date_difference_days": None}, {"reason_code": "DIFFERENT"},
    {"lineage": {"source": "changed", "flag": True}}, {"lineage": {"source": "original", "flag": 1}},
])
def test_single_existing_identity_with_different_content_is_rejected(run_repository, changes: dict[str, object]) -> None:  # noqa: F811
    boundary, run_id = run_repository
    first = _item()
    with boundary.transaction(TENANT) as connection:
        PostgresReconciliationRepository(connection).append_result(tenant_id=TENANT, run_id=run_id, **first)
    before = _state(boundary, run_id)
    with pytest.raises(PostgresReconciliationIntegrityError), boundary.transaction(TENANT) as connection:
        PostgresReconciliationRepository(connection).append_result(
            tenant_id=TENANT, run_id=run_id, **(first | changes),
        )
    assert _state(boundary, run_id) == before


def test_identical_single_and_batch_retry_accept_numeric_and_jsonb_equivalence(run_repository) -> None:  # noqa: F811
    boundary, run_id = run_repository
    first = _item()
    equivalent = _item(confidence="0.90000000", amount_difference="0.000000000000000000",
                       lineage={"flag": True, "source": "original"})
    with boundary.transaction(TENANT) as connection:
        repo = PostgresReconciliationRepository(connection)
        created = repo.append_result(tenant_id=TENANT, run_id=run_id, **first)
        replay = repo.append_result(tenant_id=TENANT, run_id=run_id, **equivalent)
        batch = repo.append_results_batch(tenant_id=TENANT, run_id=run_id, items=[equivalent])
    assert created["id"] == replay["id"] == batch[0]["id"]
    rows, checkpoints = _state(boundary, run_id)
    assert len(rows) == 1 and checkpoints == []
    assert Decimal(rows[0]["amount_difference"]) == Decimal("0")


@pytest.mark.parametrize("chunk_size", [1, 100])
@pytest.mark.parametrize("changed", [False, True])
def test_same_identity_twice_in_one_batch_is_rejected_without_writes(
    run_repository, chunk_size: int, changed: bool,  # noqa: F811
) -> None:
    boundary, run_id = run_repository
    first = _item()
    second = _item(amount_difference="4") if changed else first.copy()
    with boundary.transaction(TENANT) as connection, pytest.raises(PostgresReconciliationIntegrityError):
        PostgresReconciliationRepository(connection).append_results_batch(
            tenant_id=TENANT, run_id=run_id, items=[first, second], chunk_size=chunk_size,
        )
        # Caller intentionally catches the Python error and commits this transaction.
    assert _state(boundary, run_id) == ([], [])


def test_batch_conflict_caught_by_caller_does_not_commit_prior_chunks(run_repository) -> None:  # noqa: F811
    boundary, run_id = run_repository
    with boundary.transaction(TENANT) as connection:
        PostgresReconciliationRepository(connection).append_result(tenant_id=TENANT, run_id=run_id, **_item())
    before = _state(boundary, run_id)
    with boundary.transaction(TENANT) as connection, pytest.raises(PostgresReconciliationIntegrityError):
        PostgresReconciliationRepository(connection).append_results_batch(
            tenant_id=TENANT, run_id=run_id, items=[_distinct(), _item(amount_difference="4")], chunk_size=1,
        )
    assert _state(boundary, run_id) == before


def test_new_partition_cannot_checkpoint_conflicting_result_even_when_caught(run_repository) -> None:  # noqa: F811
    boundary, run_id = run_repository
    with boundary.transaction(TENANT) as connection:
        PostgresReconciliationRepository(connection).append_partition(
            tenant_id=TENANT, run_id=run_id, partition_key="first", input_count=2,
            results=(_item(),), worker_id="worker",
        )
    before = _state(boundary, run_id)
    with boundary.transaction(TENANT) as connection, pytest.raises(PostgresReconciliationIntegrityError):
        PostgresReconciliationRepository(connection).append_partition(
            tenant_id=TENANT, run_id=run_id, partition_key="second", input_count=2,
            results=(_distinct(), _item(amount_difference="4")), worker_id="worker",
        )
    assert _state(boundary, run_id) == before


def test_concurrent_changed_results_allow_one_and_reject_the_other(run_repository) -> None:  # noqa: F811
    boundary, run_id = run_repository
    barrier = Barrier(2)

    def attempt(amount: str) -> str:
        barrier.wait(timeout=15)
        try:
            with boundary.transaction(TENANT) as connection:
                PostgresReconciliationRepository(connection).append_results_batch(
                    tenant_id=TENANT, run_id=run_id, items=[_item(amount_difference=amount)],
                )
        except PostgresReconciliationIntegrityError:
            return "denied"
        return "accepted"

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(attempt, "0")
        second = pool.submit(attempt, "4")
        assert sorted((first.result(timeout=30), second.result(timeout=30))) == ["accepted", "denied"]
    rows, checkpoints = _state(boundary, run_id)
    assert len(rows) == 1 and checkpoints == []


def test_successful_batch_does_not_commit_callers_transaction(owned_collision_database, run_repository) -> None:  # noqa: F811
    import psycopg

    boundary, run_id = run_repository
    with psycopg.connect(owned_collision_database.app_dsn) as connection:
        set_local_tenant_scope(connection, TENANT)
        PostgresReconciliationRepository(connection).append_results_batch(
            tenant_id=TENANT, run_id=run_id, items=[_item()],
        )
        connection.rollback()
    assert _state(boundary, run_id) == ([], [])


def test_batch_preserves_existing_same_named_caller_savepoint(run_repository) -> None:  # noqa: F811
    boundary, run_id = run_repository
    with boundary.transaction(TENANT) as connection:
        connection.execute("SAVEPOINT reconforge_exception_write")
        PostgresReconciliationRepository(connection).append_results_batch(
            tenant_id=TENANT, run_id=run_id, items=[_item()],
        )
        connection.execute("ROLLBACK TO SAVEPOINT reconforge_exception_write")
        connection.execute("RELEASE SAVEPOINT reconforge_exception_write")
    assert _state(boundary, run_id) == ([], [])


def test_optional_date_none_and_zero_are_not_equal(run_repository) -> None:  # noqa: F811
    boundary, run_id = run_repository
    with boundary.transaction(TENANT) as connection:
        PostgresReconciliationRepository(connection).append_result(
            tenant_id=TENANT, run_id=run_id, **_item(date_difference_days=None),
        )
    before = _state(boundary, run_id)
    with pytest.raises(PostgresReconciliationIntegrityError), boundary.transaction(TENANT) as connection:
        PostgresReconciliationRepository(connection).append_result(
            tenant_id=TENANT, run_id=run_id, **_item(date_difference_days=0),
        )
    assert _state(boundary, run_id) == before


@pytest.mark.parametrize("operation", ["single_result", "result_batch", "exception_batch", "partition"])
def test_autocommit_connection_fails_before_result_or_checkpoint_writes(
    owned_collision_database, run_repository, operation: str,  # noqa: F811
) -> None:
    import psycopg

    boundary, run_id = run_repository
    exception = {"exception_type": "data_quality", "source_side": "Left", "source_id": "synthetic",
                 "title": "Synthetic", "explanation": "Synthetic", "severity": "Low", "risk_score": "0",
                 "reason_code": "INVALID", "evidence": {}}
    with psycopg.connect(owned_collision_database.app_dsn, autocommit=True) as connection:
        connection.execute("SELECT set_config('app.tenant_id', %s, false)", (TENANT,))
        repo = PostgresReconciliationRepository(connection)
        with pytest.raises(psycopg.errors.NoActiveSqlTransaction):
            if operation == "single_result":
                repo.append_result(tenant_id=TENANT, run_id=run_id, **_item())
            elif operation == "result_batch":
                repo.append_results_batch(tenant_id=TENANT, run_id=run_id, items=[_item()])
            elif operation == "exception_batch":
                repo.append_exceptions_batch(tenant_id=TENANT, run_id=run_id, items=[exception])
            else:
                repo.append_partition(tenant_id=TENANT, run_id=run_id, partition_key="autocommit", input_count=2,
                                      results=(_item(),), worker_id="worker")
    assert _state(boundary, run_id) == ([], [])


def test_5000_exception_rows_fit_postgres_protocol_parameter_ceiling(run_repository) -> None:  # noqa: F811
    boundary, run_id = run_repository
    items = [{"exception_type": "data_quality", "source_side": "Left", "source_id": f"synthetic-{index}",
              "title": "Synthetic", "explanation": "Synthetic", "severity": "Low", "risk_score": "0",
              "reason_code": "INVALID", "evidence": {}} for index in range(5000)]
    # The insert uses 13 parameters per row; the verification uses 12 per row plus one tenant.
    assert 13 * len(items) <= 65535 and 12 * len(items) + 1 <= 65535
    with boundary.transaction(TENANT) as connection:
        rows = PostgresReconciliationRepository(connection).append_exceptions_batch(
            tenant_id=TENANT, run_id=run_id, items=items, chunk_size=5000,
        )
    assert len(rows) == len(items)
