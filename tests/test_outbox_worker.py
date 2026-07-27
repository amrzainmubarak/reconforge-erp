from __future__ import annotations

import sqlite3
from pathlib import Path
from threading import Event

import pytest

from reconforge.db import connect, run_migrations
from reconforge.platform.common import append_outbox_event
from reconforge.workers.outbox import OutboxWorker, OutboxWorkerError, OutboxWorkerSettings


def _seed_event(db_path: Path, event_id: str = "worker-event") -> None:
    connection = connect(db_path)
    try:
        append_outbox_event(
            connection,
            event_id=event_id,
            event_type="worker.test",
            aggregate_type="test",
            aggregate_id=event_id,
            payload={"ok": True},
        )
        connection.commit()
    finally:
        connection.close()


def test_outbox_worker_uses_fresh_connections_and_publishes_once(tmp_path: Path) -> None:
    db_path = tmp_path / "worker.db"
    run_migrations(db_path)
    _seed_event(db_path)
    opened: list[sqlite3.Connection] = []
    published: list[str] = []

    def connection_factory() -> sqlite3.Connection:
        connection = connect(db_path)
        opened.append(connection)
        return connection

    worker = OutboxWorker(
        connection_factory,
        publisher=lambda event: published.append(event.id),
        settings=OutboxWorkerSettings(worker_id="worker-a", poll_interval_seconds=0, batch_size=10),
    )
    summary = worker.run(max_cycles=2)

    assert summary.cycles == 2
    assert summary.claimed == 1
    assert summary.published == 1
    assert published == ["worker-event"]
    assert len(opened) == 2
    for connection in opened:
        with pytest.raises(sqlite3.ProgrammingError):
            _ = connection.in_transaction


def test_outbox_worker_preserves_retry_and_dead_letter_state(tmp_path: Path) -> None:
    db_path = tmp_path / "worker-fail.db"
    run_migrations(db_path)
    _seed_event(db_path, "worker-fail")
    worker = OutboxWorker(
        lambda: connect(db_path),
        publisher=lambda _event: (_ for _ in ()).throw(RuntimeError("transport offline")),
        settings=OutboxWorkerSettings(
            worker_id="worker-fail",
            poll_interval_seconds=0,
            batch_size=1,
            max_attempts=1,
        ),
    )

    summary = worker.process_once()
    assert summary.failed == 1
    assert summary.dead_lettered == 1
    connection = connect(db_path)
    try:
        row = connection.execute(
            "SELECT attempts, dead_lettered_at, last_error FROM outbox_events WHERE id = ?",
            ("worker-fail",),
        ).fetchone()
        assert row["attempts"] == 1
        assert row["dead_lettered_at"] is not None
        assert row["last_error"] == "transport offline"
    finally:
        connection.close()


def test_outbox_worker_stop_event_prevents_polling(tmp_path: Path) -> None:
    db_path = tmp_path / "worker-stop.db"
    run_migrations(db_path)
    stop = Event()
    stop.set()
    opened = 0

    def connection_factory() -> sqlite3.Connection:
        nonlocal opened
        opened += 1
        return connect(db_path)

    worker = OutboxWorker(
        connection_factory,
        publisher=lambda _event: None,
        settings=OutboxWorkerSettings(worker_id="worker-stop", poll_interval_seconds=0),
    )
    assert worker.run(stop_event=stop) == worker.run(stop_event=stop)
    assert opened == 0


def test_outbox_worker_rejects_invalid_settings_and_cycle_counts() -> None:
    with pytest.raises(OutboxWorkerError):
        OutboxWorkerSettings(worker_id="", batch_size=1)
    with pytest.raises(OutboxWorkerError):
        OutboxWorkerSettings(worker_id="worker", batch_size=0)

    worker = OutboxWorker(
        lambda: connect(":memory:"),
        publisher=lambda _event: None,
        settings=OutboxWorkerSettings(worker_id="worker"),
    )
    with pytest.raises(OutboxWorkerError, match="max_cycles"):
        worker.run(max_cycles=0)
