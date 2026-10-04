"""Real SQLite leases, same-identity races, crash recovery and atomic evidence."""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

from reconforge.application.outbox import OutboxError
from reconforge.benchmark.outbox_recovery import measure_bounded_recovery
from reconforge.db import connect, run_migrations
from reconforge.db.schema import OUTBOX_DELIVERY_MIGRATION_SQL, OUTBOX_SCHEMA_SQL
from reconforge.infrastructure.outbox_fencing_schema import (
    SQLITE_OUTBOX_FENCING_GUARD_SQL,
    SQLITE_OUTBOX_FENCING_MIGRATION_SQL,
)
from reconforge.infrastructure.sqlite_outbox import OUTBOX_RECOVERY_SELECT_SQL, SQLiteOutboxRepository
from reconforge.platform.common import append_outbox_event
from reconforge.platform.outbox import OutboxService
from reconforge.workers.outbox import OutboxWorker, OutboxWorkerSettings


@pytest.fixture
def database(tmp_path: Path) -> Path:
    path = tmp_path / "outbox-fencing.db"
    run_migrations(path)
    with connect(path) as connection:
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(outbox_events)")}
        if "lease_generation" not in columns:
            # Independent slice gate; central migration registration is integrated by Amr.
            connection.executescript(SQLITE_OUTBOX_FENCING_MIGRATION_SQL)
    return path


def _seed(path: Path, count: int = 1) -> None:
    with connect(path) as connection:
        for index in range(count):
            append_outbox_event(
                connection, event_id=f"event-{index}", event_type="test.created",
                aggregate_type="test", aggregate_id=f"item-{index}", payload={"synthetic": True},
            )
        connection.commit()


def _expire(path: Path) -> None:
    with connect(path) as connection:
        connection.execute("UPDATE outbox_events SET locked_at='2000-01-01T00:00:00Z' WHERE locked_at IS NOT NULL")
        connection.commit()


def test_reused_worker_identity_cannot_acknowledge_or_fail_new_generation(database: Path) -> None:
    _seed(database)
    with connect(database) as connection:
        repository = SQLiteOutboxRepository(connection)
        old = repository.claim_pending(worker_id="shared-worker")[0]
    _expire(database)
    with connect(database) as connection:
        repository = SQLiteOutboxRepository(connection)
        current = repository.claim_pending(worker_id="shared-worker")[0]
        assert current.lease_generation == old.lease_generation + 1 == 2
        for generation in (old.lease_generation, None):
            with pytest.raises(OutboxError):
                repository.mark_published(event_id=old.id, worker_id="shared-worker", lease_generation=generation)
            with pytest.raises(OutboxError):
                repository.mark_failed(
                    event_id=old.id, worker_id="shared-worker", error="stale", lease_generation=generation
                )
        repository.mark_published(
            event_id=current.id, worker_id="shared-worker", lease_generation=current.lease_generation
        )
        actions = [row[0] for row in connection.execute("SELECT action FROM outbox_delivery_evidence ORDER BY evidence_id")]
        assert actions == ["claimed", "expired", "claimed", "published"]


def test_expired_unreclaimed_claim_cannot_publish_fail_or_start_delivery(database: Path) -> None:
    _seed(database)
    with connect(database) as connection:
        claim = SQLiteOutboxRepository(connection).claim_pending(worker_id="worker")[0]
    _expire(database)
    with connect(database) as connection:
        repository = SQLiteOutboxRepository(connection)
        with pytest.raises(OutboxError, match="expired"):
            repository.assert_claim(event_id=claim.id, worker_id="worker", lease_generation=claim.lease_generation)
        with pytest.raises(OutboxError):
            repository.mark_published(event_id=claim.id, worker_id="worker", lease_generation=claim.lease_generation)
        with pytest.raises(OutboxError):
            repository.mark_failed(event_id=claim.id, worker_id="worker", error="stale", lease_generation=claim.lease_generation)
        assert connection.execute("SELECT attempts FROM outbox_events").fetchone()[0] == 0


def test_application_service_propagates_the_exact_fencing_token(database: Path) -> None:
    _seed(database)
    with connect(database) as connection:
        published: list[tuple[str, int]] = []
        result = OutboxService(connection).process_once(
            publisher=lambda event: published.append((event.id, event.lease_generation)),
            worker_id="worker",
        )
        assert result.claimed == result.published == 1
        assert result.failed == result.dead_lettered == 0
        assert published == [("event-0", 1)]
        assert connection.execute("SELECT lease_generation,published_at FROM outbox_events").fetchone()[0] == 1
        assert [row[0] for row in connection.execute(
            "SELECT action FROM outbox_delivery_evidence ORDER BY evidence_id"
        )] == ["claimed", "published"]


def test_omitted_generation_acknowledges_only_a_current_first_claim(database: Path) -> None:
    _seed(database)
    with connect(database) as connection:
        repository = SQLiteOutboxRepository(connection)
        claim = repository.claim_pending(worker_id="worker")[0]
        assert claim.lease_generation == 1
        repository.mark_published(event_id=claim.id, worker_id="worker")
        assert repository.list_events(status="published")[0].lease_generation == 1


def test_worker_uses_a_fenced_claim_and_fresh_connection(database: Path) -> None:
    _seed(database)
    published: list[tuple[str, int]] = []
    worker = OutboxWorker(
        lambda: connect(database),
        publisher=lambda event: published.append((event.id, event.lease_generation)),
        settings=OutboxWorkerSettings(worker_id="worker", poll_interval_seconds=0, batch_size=1),
    )
    result = worker.process_once()
    assert result.claimed == result.published == 1
    assert published == [("event-0", 1)]
    with connect(database) as connection:
        assert SQLiteOutboxRepository(connection).list_events(status="published")[0].lease_generation == 1


def test_crash_on_final_attempt_is_terminal_bounded_and_replayable(database: Path) -> None:
    _seed(database, 3)
    with connect(database) as connection:
        claims = SQLiteOutboxRepository(connection).claim_pending(worker_id="crashed", limit=3, max_attempts=1)
        assert len(claims) == 3
    _expire(database)
    with connect(database) as connection:
        repository = SQLiteOutboxRepository(connection)
        assert repository.recover_expired(limit=2, max_attempts=1) == 2
        assert len(repository.list_events(status="dead_letter")) == 2
        assert repository.recover_expired(limit=2, max_attempts=1) == 1
        assert repository.recover_expired(limit=2, max_attempts=1) == 0
        assert repository.claim_pending(worker_id="replacement", max_attempts=1) == []
        repository.requeue_dead_letter(event_id=claims[0].id)
        replay = repository.claim_pending(worker_id="crashed", max_attempts=1)[0]
        assert replay.lease_generation == 2
        assert replay.attempts == 0
        repository.mark_published(event_id=replay.id, worker_id="crashed", lease_generation=replay.lease_generation)


def test_same_worker_identity_concurrent_claims_have_one_owner(database: Path) -> None:
    _seed(database)
    barrier = Barrier(2)

    def claim() -> list[object]:
        with connect(database) as connection:
            barrier.wait(timeout=10)
            return list(SQLiteOutboxRepository(connection).claim_pending(worker_id="shared-worker", limit=1))

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: claim(), range(2)))
    assert sorted(len(result) for result in results) == [0, 1]
    with connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM outbox_delivery_evidence").fetchone()[0] == 1


def test_recovery_exact_update_failure_rolls_back_its_transaction(database: Path) -> None:
    _seed(database)
    with connect(database) as connection:
        repository = SQLiteOutboxRepository(connection)
        repository.claim_pending(worker_id="worker")
        connection.execute("UPDATE outbox_events SET locked_at='2000-01-01T00:00:00Z'")
        connection.commit()
        connection.execute("""CREATE TRIGGER ignore_expired_recovery BEFORE UPDATE ON outbox_events
            WHEN NEW.last_error='LEASE_EXPIRED' BEGIN SELECT RAISE(IGNORE); END""")
        connection.commit()
        with pytest.raises(OutboxError, match="lease changed"):
            repository.recover_expired(max_attempts=1)
        assert not connection.in_transaction
        assert tuple(connection.execute("SELECT attempts,last_error FROM outbox_events").fetchone()) == (0, None)


@pytest.mark.parametrize("operation", ["claim", "recover", "publish"])
def test_evidence_failure_rolls_back_delivery_state(database: Path, operation: str) -> None:
    _seed(database)
    with connect(database) as connection:
        repository = SQLiteOutboxRepository(connection)
        claim = None if operation == "claim" else repository.claim_pending(worker_id="worker")[0]
        if operation == "recover":
            connection.execute("UPDATE outbox_events SET locked_at='2000-01-01T00:00:00Z'")
            connection.commit()
        before = tuple(connection.execute("SELECT * FROM outbox_events").fetchone())
        connection.execute("""CREATE TRIGGER inject_evidence_failure BEFORE INSERT ON outbox_delivery_evidence
            BEGIN SELECT RAISE(ABORT,'synthetic evidence failure'); END""")
        connection.commit()
        with pytest.raises(OutboxError):
            if operation == "claim":
                repository.claim_pending(worker_id="worker")
            elif operation == "recover":
                repository.recover_expired(max_attempts=1)
            else:
                assert claim is not None
                repository.mark_published(event_id=claim.id, worker_id="worker", lease_generation=claim.lease_generation)
        assert tuple(connection.execute("SELECT * FROM outbox_events").fetchone()) == before


def test_delivery_evidence_and_generation_are_protected(database: Path) -> None:
    _seed(database)
    with connect(database) as connection:
        SQLiteOutboxRepository(connection).claim_pending(worker_id="worker")
        for statement in (
            "UPDATE outbox_events SET lease_generation=0",
            "UPDATE outbox_events SET lease_generation=3",
            "UPDATE outbox_delivery_evidence SET worker_id='forged'",
            "DELETE FROM outbox_delivery_evidence",
        ):
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(statement)
            connection.rollback()


def test_storage_rejects_unfenced_insert_direct_publish_and_forged_evidence(database: Path) -> None:
    _seed(database)
    with connect(database) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="initial generation"):
            connection.execute(
                """INSERT INTO outbox_events(
                id,event_type,aggregate_type,aggregate_id,payload_json,created_at,available_at,
                lease_generation,lease_generation_floor)
                VALUES('unfenced','test','test','unfenced','{}','2026-10-03T00:00:00Z',
                       '2026-10-03T00:00:00Z',0,2)"""
            )
        connection.rollback()
        with pytest.raises(sqlite3.IntegrityError, match="live claimed generation"):
            connection.execute(
                """UPDATE outbox_events SET published_at='2026-10-03T00:00:00Z',
                locked_at=NULL,locked_by=NULL,last_error=NULL WHERE id='event-0'"""
            )
        connection.rollback()

        repository = SQLiteOutboxRepository(connection)
        claim = repository.claim_pending(worker_id="worker")[0]
        with pytest.raises(sqlite3.IntegrityError, match="evidence admission"):
            connection.execute(
                """INSERT INTO outbox_delivery_evidence(
                event_id,lease_generation,action,worker_id,occurred_at,attempts)
                VALUES(?,?,'published','forged','2026-10-03T00:00:00Z',?)""",
                (claim.id, claim.lease_generation, claim.attempts),
            )
        connection.rollback()
        repository.mark_published(
            event_id=claim.id,
            worker_id="worker",
            lease_generation=claim.lease_generation,
        )


def test_storage_verifier_rejects_retained_post_floor_evidence_gap(database: Path) -> None:
    _seed(database)
    with connect(database) as connection:
        claim = SQLiteOutboxRepository(connection).claim_pending(worker_id="worker")[0]
        connection.execute("DROP TRIGGER outbox_delivery_evidence_no_delete")
        connection.execute("DELETE FROM outbox_delivery_evidence WHERE event_id=?", (claim.id,))
        connection.commit()
        with pytest.raises(OutboxError, match="Retained outbox delivery evidence is invalid"):
            SQLiteOutboxRepository(connection)


def test_verified_temporary_restore_can_reinstall_fencing_guard_bundle(database: Path) -> None:
    _seed(database)
    with connect(database) as connection:
        connection.executescript(SQLITE_OUTBOX_FENCING_GUARD_SQL)
        repository = SQLiteOutboxRepository(connection)
        claim = repository.claim_pending(worker_id="worker")[0]
        repository.mark_published(
            event_id=claim.id,
            worker_id="worker",
            lease_generation=claim.lease_generation,
        )


@pytest.mark.parametrize("generation", [0, -1, True, 2**63, "1"])
def test_invalid_generation_is_rejected_before_storage(database: Path, generation: object) -> None:
    with connect(database) as connection, pytest.raises(OutboxError, match="lease_generation"):
            SQLiteOutboxRepository(connection).mark_published(
                event_id="missing", worker_id="worker", lease_generation=generation  # type: ignore[arg-type]
            )


def test_populated_upgrade_fences_ambiguous_preupgrade_worker_identity() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    try:
        connection.executescript(OUTBOX_SCHEMA_SQL + OUTBOX_DELIVERY_MIGRATION_SQL)
        connection.execute(
            """INSERT INTO outbox_events(id,event_type,aggregate_type,aggregate_id,payload_json,created_at,
            available_at,locked_at,locked_by,attempts) VALUES('legacy','test','test','item','{}',
            '2000-01-01T00:00:00Z','2000-01-01T00:00:00Z','2099-01-01T00:00:00Z','reused-worker',2)"""
        )
        connection.execute(
            """INSERT INTO outbox_events(id,event_type,aggregate_type,aggregate_id,payload_json,created_at,
            available_at,published_at,attempts) VALUES('legacy-published','test','test','item','{}',
            '2000-01-01T00:00:00Z','2000-01-01T00:00:00Z','2000-01-01T00:00:00Z',0)"""
        )
        connection.commit()
        connection.executescript(SQLITE_OUTBOX_FENCING_MIGRATION_SQL)
        repository = SQLiteOutboxRepository(connection)
        events = {event.id: event for event in repository.list_events(status="all")}
        assert events["legacy"].lease_generation == events["legacy"].lease_generation_floor == 2
        assert events["legacy-published"].lease_generation == events["legacy-published"].lease_generation_floor == 2
        with pytest.raises(OutboxError):
            repository.assert_claim(event_id="legacy", worker_id="reused-worker", lease_generation=2)
        with pytest.raises(OutboxError):
            repository.mark_published(event_id="legacy", worker_id="reused-worker", lease_generation=2)
        with pytest.raises(OutboxError):
            repository.mark_failed(
                event_id="legacy", worker_id="reused-worker", error="legacy", lease_generation=2
            )
        with pytest.raises(OutboxError):
            repository.mark_published(event_id="legacy", worker_id="reused-worker")
        connection.execute("UPDATE outbox_events SET locked_at='2000-01-01T00:00:00Z' WHERE id='legacy'")
        connection.commit()
        recovered = repository.claim_pending(worker_id="reused-worker")[0]
        assert recovered.lease_generation == 3 and recovered.attempts == 3
        with pytest.raises(OutboxError):
            repository.mark_published(event_id="legacy", worker_id="reused-worker")
        repository.mark_published(event_id="legacy", worker_id="reused-worker", lease_generation=3)
    finally:
        connection.close()


def test_bounded_recovery_profile_1000_expired_events(database: Path, record_property: object) -> None:
    _seed(database, 1000)
    with connect(database) as connection:
        repository = SQLiteOutboxRepository(connection)
        assert len(repository.claim_pending(worker_id="crashed", limit=1000, max_attempts=1)) == 1000
    _expire(database)
    with connect(database) as connection:
        repository = SQLiteOutboxRepository(connection)
        result = measure_bounded_recovery(
            backend="sqlite", events=1000, batch_limit=100,
            recover=lambda limit: repository.recover_expired(limit=limit, max_attempts=1),
        )
        assert result.calls == 11 and result.recovered == 1000 and result.largest_batch == 100
        assert len(repository.list_events(status="dead_letter", limit=1000)) == 1000
        assert connection.execute("SELECT COUNT(*) FROM outbox_delivery_evidence").fetchone()[0] == 2000
        plan = [row[3] for row in connection.execute(
            "EXPLAIN QUERY PLAN " + OUTBOX_RECOVERY_SELECT_SQL, ("2099-01-01T00:00:00Z", 100),
        )]
        assert any("idx_outbox_expired_lease" in item for item in plan)
        assert not any("TEMP B-TREE" in item for item in plan)
        record_property("amr_recovery", result.to_dict())  # type: ignore[operator]
        record_property("amr_recovery_query_plan", plan)  # type: ignore[operator]
