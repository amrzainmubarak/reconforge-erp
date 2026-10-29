"""Fail-closed exception identity and checkpoint tests on synthetic data."""

from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier

import pytest

from reconforge.infrastructure.postgres import (
    PostgresConnectionFactory,
    PostgresSettings,
    PostgresTenantBoundary,
    set_local_tenant_scope,
)
from reconforge.infrastructure.postgres_reconciliation import (
    PostgresReconciliationIntegrityError,
    PostgresReconciliationRepository,
)
from reconforge.workers.postgres_reconciliation import (
    LocalDeterministicMatcherAdapter,
    PostgresReconciliationWorkerError,
    ReconciliationExecutionContext,
)
from tests.test_reconciliation_worker_organization_native import owned_organization_database

# Reuse the owned-server fixture's provisioning unchanged, but migrate its
# randomly named synthetic database once for this test module.
owned_collision_database = pytest.fixture(scope="module")(owned_organization_database.__wrapped__)
TENANT = "org-tenant"


def test_empty_exception_batch_does_not_touch_database_or_validate_scope() -> None:
    class NoDatabaseAccess:
        def execute(self, *_: object) -> object:
            raise AssertionError("empty exception batch must not access the database")

    repository = PostgresReconciliationRepository(NoDatabaseAccess())
    assert repository.append_exceptions_batch(tenant_id="", run_id="", items=[]) == []


def _historical_collision_payloads() -> list[tuple[str, dict[str, object]]]:
    """Static examples model the old adapter output; direct repository input remains untrusted."""
    return [
        ("partition-a", {"exception_type": "data_quality", "source_side": "Left", "source_id": "same",
                         "title": "Missing reconciliation date", "explanation": "Date is missing.",
                         "severity": "Medium", "risk_score": "0.3", "reason_code": "MISSING_DATE",
                         "evidence": {"department": "A"}, "exception_id": "EXC-E08C0DE45BBA911C2F49"}),
        ("partition-b", {"exception_type": "data_quality", "source_side": "Left", "source_id": "same",
                         "title": "Missing reconciliation date", "explanation": "Date is missing.",
                         "severity": "Medium", "risk_score": "0.3", "reason_code": "MISSING_DATE",
                         "evidence": {"department": "B"}, "exception_id": "EXC-103409177B925BDDB025"}),
    ]


def test_canonical_source_guard_rejects_the_historical_collision_input() -> None:
    left = tuple(
        {"source_id": source, "amount_decimal": Decimal("5.00"), "currency_code": "USD", "date_original": "",
         "reference_original": "SYN", "valid": True, "attributes_json": {"id": "same", "department": department}}
        for source, department in (("left-one", "A"), ("left-two", "B"))
    )
    right = tuple(
        {"source_id": source, "amount_decimal": Decimal("5.00"), "currency_code": "USD",
         "date_original": "2026-10-01", "reference_original": "SYN", "valid": True,
         "attributes_json": {"department": department}}
        for source, department in (("right-one", "A"), ("right-two", "B"))
    )
    context = ReconciliationExecutionContext(
        run={"rule_json": {"partition_fields": ["department"],
                           "record_identity_policy": "canonical-multiset-occurrence-v1"}},
        left_inputs=left, right_inputs=right, heartbeat=lambda _: {}, cancellation_requested=lambda: False,
    )
    with pytest.raises(PostgresReconciliationWorkerError, match="conflict with canonical source"):
        tuple(LocalDeterministicMatcherAdapter().iter_partition_results(context))


def _storage_payload(exception: dict[str, object]) -> dict[str, object]:
    """Test storage with the known engine ID preserved in synthetic evidence.

    The production adapter bridge does not exist yet; this is an explicit
    test transformation, not evidence of an implemented bridge.
    """
    value = dict(exception)
    engine_id = value.pop("exception_id")
    evidence = dict(value["evidence"])  # type: ignore[arg-type]
    evidence["test_engine_exception_id"] = engine_id
    value["evidence"] = evidence
    return value


def _collision_identity(value: dict[str, object]) -> tuple[object, ...]:
    return tuple(value[key] for key in ("exception_type", "source_side", "source_id", "reason_code"))


def test_synthetic_storage_payloads_have_distinct_evidence_and_one_identity() -> None:
    outputs = _historical_collision_payloads()
    assert len(outputs) == 2 and outputs[0][0] != outputs[1][0]
    assert outputs[0][1]["exception_id"] != outputs[1][1]["exception_id"]
    assert outputs[0][1]["evidence"] != outputs[1][1]["evidence"]
    assert _collision_identity(outputs[0][1]) == _collision_identity(outputs[1][1])


@pytest.fixture
def run_repository(owned_collision_database, request):
    factory = PostgresConnectionFactory(PostgresSettings(dsn=owned_collision_database.app_dsn, require_tls=False))
    boundary = PostgresTenantBoundary(factory)
    run_id = "collision-" + hashlib.sha256(request.node.name.encode("utf-8")).hexdigest()[:16]
    with boundary.transaction(TENANT) as connection:
        repository = PostgresReconciliationRepository(connection)
        repository.create_run(tenant_id=TENANT, run_id=run_id, name="Synthetic", left_source="left",
                              right_source="right", algorithm_version="synthetic-v1", rule={},
                              input_hash="synthetic", actor_id="maker")
        for side in ("Left", "Right"):
            repository.register_input(tenant_id=TENANT, run_id=run_id, side=side, source_id=side,
                                      record_hash="hash-" + side, amount="5.00", currency_code="USD")
        repository.claim_run(tenant_id=TENANT, run_id=run_id, worker_id="worker", lease_seconds=300)
    return boundary, run_id


def _rows(boundary: PostgresTenantBoundary, run_id: str) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    with boundary.transaction(TENANT) as connection:
        repository = PostgresReconciliationRepository(connection)
        return (repository.list_exceptions(tenant_id=TENANT, run_id=run_id),
                repository.list_checkpoints(tenant_id=TENANT, run_id=run_id))


def test_same_chunk_collision_rejected_before_writes(run_repository) -> None:
    boundary, run_id = run_repository
    first, second = (_storage_payload(value) for _, value in _historical_collision_payloads())
    conflict = None
    try:
        with boundary.transaction(TENANT) as connection:
            PostgresReconciliationRepository(connection).append_exceptions_batch(
                tenant_id=TENANT, run_id=run_id, items=[first, second], chunk_size=100,
            )
    except PostgresReconciliationIntegrityError as exc:
        conflict = exc
    assert _rows(boundary, run_id) == ([], [])
    assert conflict is not None


def test_cross_chunk_collision_rejected_before_writes(run_repository) -> None:
    boundary, run_id = run_repository
    first, second = (_storage_payload(value) for _, value in _historical_collision_payloads())
    conflict = None
    try:
        with boundary.transaction(TENANT) as connection:
            PostgresReconciliationRepository(connection).append_exceptions_batch(
                tenant_id=TENANT, run_id=run_id, items=[first, second], chunk_size=1,
            )
    except PostgresReconciliationIntegrityError as exc:
        conflict = exc
    assert _rows(boundary, run_id) == ([], [])
    assert conflict is not None


def test_duplicate_identical_items_in_one_batch_fail_before_writing(run_repository) -> None:
    boundary, run_id = run_repository
    first = _storage_payload(_historical_collision_payloads()[0][1])
    with pytest.raises(PostgresReconciliationIntegrityError), boundary.transaction(TENANT) as connection:
        PostgresReconciliationRepository(connection).append_exceptions_batch(
            tenant_id=TENANT, run_id=run_id, items=[first, dict(first)],
        )
    assert _rows(boundary, run_id) == ([], [])


def test_identical_single_exception_retry_returns_existing_row(run_repository) -> None:
    boundary, run_id = run_repository
    first = _storage_payload(_historical_collision_payloads()[0][1])
    with boundary.transaction(TENANT) as connection:
        original = PostgresReconciliationRepository(connection).append_exception(
            tenant_id=TENANT, run_id=run_id, **first,
        )
    with boundary.transaction(TENANT) as connection:
        repeated = PostgresReconciliationRepository(connection).append_exception(
            tenant_id=TENANT, run_id=run_id, **first,
        )
    assert original["id"] == repeated["id"]
    assert original["evidence_json"] == repeated["evidence_json"]
    assert len(_rows(boundary, run_id)[0]) == 1


def test_identical_batch_retry_returns_existing_row(run_repository) -> None:
    boundary, run_id = run_repository
    first = _storage_payload(_historical_collision_payloads()[0][1])
    with boundary.transaction(TENANT) as connection:
        original = PostgresReconciliationRepository(connection).append_exceptions_batch(
            tenant_id=TENANT, run_id=run_id, items=[first],
        )
    with boundary.transaction(TENANT) as connection:
        repeated = PostgresReconciliationRepository(connection).append_exceptions_batch(
            tenant_id=TENANT, run_id=run_id, items=[first],
        )
    assert len(original) == len(repeated) == 1
    assert original[0]["id"] == repeated[0]["id"]
    assert original[0]["evidence_json"] == repeated[0]["evidence_json"]
    assert len(_rows(boundary, run_id)[0]) == 1


def test_jsonb_order_and_numeric_scale_replay_as_equal(run_repository) -> None:
    boundary, run_id = run_repository
    first = _storage_payload(_historical_collision_payloads()[0][1])
    first["evidence"] = {"a": 1, "b": 2}
    second = {**first, "risk_score": "0.30000000", "evidence": {"b": 2, "a": 1}}
    with boundary.transaction(TENANT) as connection:
        original = PostgresReconciliationRepository(connection).append_exceptions_batch(
            tenant_id=TENANT, run_id=run_id, items=[first],
        )
    with boundary.transaction(TENANT) as connection:
        replay = PostgresReconciliationRepository(connection).append_exceptions_batch(
            tenant_id=TENANT, run_id=run_id, items=[second],
        )
    assert original[0]["id"] == replay[0]["id"]
    assert len(_rows(boundary, run_id)[0]) == 1


def test_concurrent_different_exception_content_has_one_winner(run_repository) -> None:
    boundary, run_id = run_repository
    first, second = (_storage_payload(value) for _, value in _historical_collision_payloads())
    start = Barrier(2)

    def attempt(item: dict[str, object]) -> str:
        start.wait(timeout=10)
        try:
            with boundary.transaction(TENANT) as connection:
                PostgresReconciliationRepository(connection).append_exceptions_batch(
                    tenant_id=TENANT, run_id=run_id, items=[item],
                )
        except PostgresReconciliationIntegrityError:
            return "denied"
        return "accepted"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(attempt, (first, second)))
    assert sorted(outcomes) == ["accepted", "denied"]
    rows, checkpoints = _rows(boundary, run_id)
    assert len(rows) == 1 and checkpoints == []
    assert rows[0]["evidence_json"] in (first["evidence"], second["evidence"])


def test_replay_compares_jsonb_types_without_treating_boolean_as_number(run_repository) -> None:
    boundary, run_id = run_repository
    first = _storage_payload(_historical_collision_payloads()[0][1])
    first["evidence"] = {"flag": True}
    second = {**first, "evidence": {"flag": 1}}
    with boundary.transaction(TENANT) as connection:
        PostgresReconciliationRepository(connection).append_exceptions_batch(tenant_id=TENANT, run_id=run_id, items=[first])
    before = _rows(boundary, run_id)
    with pytest.raises(PostgresReconciliationIntegrityError), boundary.transaction(TENANT) as connection:
        PostgresReconciliationRepository(connection).append_exceptions_batch(tenant_id=TENANT, run_id=run_id, items=[second])
    assert _rows(boundary, run_id) == before


def test_workflow_status_change_does_not_make_matching_content_conflict(run_repository) -> None:
    boundary, run_id = run_repository
    first = _storage_payload(_historical_collision_payloads()[0][1])
    with boundary.transaction(TENANT) as connection:
        original = PostgresReconciliationRepository(connection).append_exception(
            tenant_id=TENANT, run_id=run_id, **first,
        )
        connection.execute(
            "UPDATE reconforge.reconciliation_exceptions SET workflow_status='Assigned' WHERE tenant_id=%s AND id=%s",
            (TENANT, original["id"]),
        )
    with boundary.transaction(TENANT) as connection:
        repeated = PostgresReconciliationRepository(connection).append_exception(
            tenant_id=TENANT, run_id=run_id, **first,
        )
    assert repeated["id"] == original["id"]
    assert repeated["workflow_status"] == "Assigned"


def test_changed_owner_is_conservatively_rejected_without_reassignment(run_repository) -> None:
    boundary, run_id = run_repository
    first = _storage_payload(_historical_collision_payloads()[0][1])
    first["owner_id"] = "original-owner"
    with boundary.transaction(TENANT) as connection:
        original = PostgresReconciliationRepository(connection).append_exception(
            tenant_id=TENANT, run_id=run_id, **first,
        )
        connection.execute(
            "UPDATE reconforge.reconciliation_exceptions SET workflow_status='Assigned',owner_id='new-owner' "
            "WHERE tenant_id=%s AND id=%s", (TENANT, original["id"]),
        )
    with pytest.raises(PostgresReconciliationIntegrityError, match="different content"), boundary.transaction(TENANT) as connection:
        PostgresReconciliationRepository(connection).append_exception(tenant_id=TENANT, run_id=run_id, **first)
    existing, _ = _rows(boundary, run_id)
    assert len(existing) == 1 and existing[0]["owner_id"] == "new-owner"
    assert existing[0]["workflow_status"] == "Assigned"


def test_second_partition_collision_preserves_first_checkpoint_and_rolls_back_second(run_repository) -> None:
    boundary, run_id = run_repository
    outputs = _historical_collision_payloads()
    first, second = (_storage_payload(value) for _, value in outputs)
    with boundary.transaction(TENANT) as connection:
        original = PostgresReconciliationRepository(connection).append_partition(
            tenant_id=TENANT, run_id=run_id, partition_key=outputs[0][0], input_count=2,
            results=(), exceptions=(first,), worker_id="worker",
        )
    before = _rows(boundary, run_id)
    # An unrelated insert ahead of the conflict verifies rollback of all writes
    # in the second transaction, not merely the collided row.
    distinct = {**second, "source_id": "unrelated-synthetic"}
    conflict = None
    try:
        with boundary.transaction(TENANT) as connection:
            PostgresReconciliationRepository(connection).append_partition(
                tenant_id=TENANT, run_id=run_id, partition_key=outputs[1][0], input_count=2,
                results=(), exceptions=(distinct, second), worker_id="worker",
            )
    except PostgresReconciliationIntegrityError as exc:
        conflict = exc
    after = _rows(boundary, run_id)
    assert after == before
    assert conflict is not None
    assert len(after[0]) == len(after[1]) == 1
    assert after[1][0]["output_hash"] == original["output_hash"]


def test_caught_collision_cannot_commit_partial_partition_writes(run_repository) -> None:
    boundary, run_id = run_repository
    outputs = _historical_collision_payloads()
    first, second = (_storage_payload(value) for _, value in outputs)
    with boundary.transaction(TENANT) as connection:
        PostgresReconciliationRepository(connection).append_partition(
            tenant_id=TENANT, run_id=run_id, partition_key=outputs[0][0], input_count=2,
            results=(), exceptions=(first,), worker_id="worker",
        )
    before = _rows(boundary, run_id)
    distinct = {**second, "source_id": "unrelated-caught"}
    result = {"left_id": "Left", "right_id": "Right", "match_type": "exact", "confidence": "1",
              "explanation": "synthetic", "amount_difference": "0", "status": "Matched", "lineage": {}}
    with boundary.transaction(TENANT) as connection:
        try:
            PostgresReconciliationRepository(connection).append_partition(
                tenant_id=TENANT, run_id=run_id, partition_key=outputs[1][0], input_count=2,
                results=(result,), exceptions=(distinct, second), worker_id="worker",
            )
        except PostgresReconciliationIntegrityError:
            pass  # A caller may catch a Python exception and then commit.
        else:
            pytest.fail("different exception content was accepted")
        assert connection.execute("SELECT 1").fetchone()[0] == 1
    assert _rows(boundary, run_id) == before
    with boundary.transaction(TENANT) as connection:
        assert PostgresReconciliationRepository(connection).list_results(tenant_id=TENANT, run_id=run_id) == []


def test_successful_partition_does_not_commit_the_callers_transaction(owned_collision_database, run_repository) -> None:
    import psycopg

    boundary, run_id = run_repository
    first = _storage_payload(_historical_collision_payloads()[0][1])
    with psycopg.connect(owned_collision_database.app_dsn) as connection:
        set_local_tenant_scope(connection, TENANT)
        PostgresReconciliationRepository(connection).append_partition(
            tenant_id=TENANT, run_id=run_id, partition_key="synthetic", input_count=1,
            results=(), exceptions=(first,), worker_id="worker",
        )
        connection.rollback()
    assert _rows(boundary, run_id) == ([], [])


def test_existing_same_named_caller_savepoint_is_preserved(run_repository) -> None:
    boundary, run_id = run_repository
    first = _storage_payload(_historical_collision_payloads()[0][1])
    with boundary.transaction(TENANT) as connection:
        connection.execute("SAVEPOINT reconforge_exception_write")
        PostgresReconciliationRepository(connection).append_partition(
            tenant_id=TENANT, run_id=run_id, partition_key="synthetic", input_count=1,
            results=(), exceptions=(first,), worker_id="worker",
        )
        connection.execute("ROLLBACK TO SAVEPOINT reconforge_exception_write")
        connection.execute("RELEASE SAVEPOINT reconforge_exception_write")
    assert _rows(boundary, run_id) == ([], [])


def test_autocommit_without_transaction_fails_before_exception_write(owned_collision_database, run_repository) -> None:
    import psycopg

    boundary, run_id = run_repository
    first = _storage_payload(_historical_collision_payloads()[0][1])
    with psycopg.connect(owned_collision_database.app_dsn, autocommit=True) as connection, pytest.raises(psycopg.Error):
        PostgresReconciliationRepository(connection).append_partition(
            tenant_id=TENANT, run_id=run_id, partition_key="synthetic", input_count=1,
            results=(), exceptions=(first,), worker_id="worker",
        )
    assert _rows(boundary, run_id) == ([], [])


def test_empty_exception_batch_works_on_autocommit_without_transaction(owned_collision_database) -> None:
    import psycopg

    with psycopg.connect(owned_collision_database.app_dsn, autocommit=True) as connection:
        assert PostgresReconciliationRepository(connection).append_exceptions_batch(
            tenant_id="", run_id="", items=[],
        ) == []


def test_caught_collision_cannot_commit_partial_exception_batch(run_repository) -> None:
    boundary, run_id = run_repository
    first, second = (_storage_payload(value) for _, value in _historical_collision_payloads())
    with boundary.transaction(TENANT) as connection:
        PostgresReconciliationRepository(connection).append_exceptions_batch(
            tenant_id=TENANT, run_id=run_id, items=[first],
        )
    before = _rows(boundary, run_id)
    distinct = {**second, "source_id": "unrelated-caught-batch"}
    with boundary.transaction(TENANT) as connection:
        try:
            PostgresReconciliationRepository(connection).append_exceptions_batch(
                tenant_id=TENANT, run_id=run_id, items=[distinct, second],
            )
        except PostgresReconciliationIntegrityError:
            pass
        else:
            pytest.fail("different exception content was accepted")
    assert _rows(boundary, run_id) == before
