from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reconforge.cli import app
from reconforge.db import connect, run_migrations
from reconforge.platform.common import append_outbox_event
from reconforge.platform.outbox import OutboxError, OutboxEvent, OutboxService

runner = CliRunner()


def _seed_event(connection, event_id: str = "evt-1") -> None:
    append_outbox_event(
        connection,
        event_id=event_id,
        event_type="test.event",
        aggregate_type="test",
        aggregate_id=event_id,
        payload={"event_id": event_id},
    )
    connection.commit()


def test_outbox_claim_publish_and_payload_are_deterministic(tmp_path: Path) -> None:
    db_path = tmp_path / "outbox.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        _seed_event(connection)
        service = OutboxService(connection)
        claimed = service.claim_pending(worker_id="worker-a", limit=10)
        assert [event.id for event in claimed] == ["evt-1"]
        assert json.loads(claimed[0].payload_json) == {"event_id": "evt-1"}
        assert service.claim_pending(worker_id="worker-b", limit=10) == []

        published: list[str] = []
        result = service.process_once(
            publisher=lambda event: published.append(event.id),
            worker_id="worker-a",
        )
        assert result.claimed == 0
        assert result.published == 0
        assert published == []

        service.mark_published(event_id="evt-1", worker_id="worker-a")
        row = connection.execute(
            "SELECT published_at, locked_at, locked_by, attempts FROM outbox_events WHERE id = 'evt-1'",
        ).fetchone()
        assert row["published_at"] is not None
        assert row["locked_at"] is None
        assert row["locked_by"] is None
        assert row["attempts"] == 0
    finally:
        connection.close()


def test_outbox_process_retries_then_dead_letters_and_can_requeue(tmp_path: Path) -> None:
    db_path = tmp_path / "outbox-retry.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        _seed_event(connection)
        service = OutboxService(connection, max_attempts=2, retry_base_seconds=0)

        def fail(_event: OutboxEvent) -> None:
            raise RuntimeError("sink unavailable")

        first = service.process_once(publisher=fail, worker_id="worker-a")
        second = service.process_once(publisher=fail, worker_id="worker-a")
        assert (first.claimed, first.failed, first.dead_lettered) == (1, 1, 0)
        assert (second.claimed, second.failed, second.dead_lettered) == (1, 1, 1)
        dead = service.list_events(status="dead_letter")
        assert len(dead) == 1
        assert dead[0].attempts == 2
        assert dead[0].last_error == "sink unavailable"

        service.requeue_dead_letter(event_id="evt-1")
        assert service.list_events(status="pending")[0].attempts == 0
    finally:
        connection.close()


def test_outbox_rejects_nested_transactions_and_invalid_claims(tmp_path: Path) -> None:
    db_path = tmp_path / "outbox-errors.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        service = OutboxService(connection)
        with pytest.raises(OutboxError, match="worker_id"):
            service.claim_pending(worker_id="", limit=1)
        with pytest.raises(OutboxError, match="between 1 and 1000"):
            service.claim_pending(worker_id="worker-a", limit=0)
        connection.execute("BEGIN IMMEDIATE")
        with pytest.raises(OutboxError, match="idle"):
            service.claim_pending(worker_id="worker-a", limit=1)
        connection.rollback()
    finally:
        connection.close()


def test_outbox_cli_lists_and_requeues_events(tmp_path: Path) -> None:
    db_path = tmp_path / "outbox-cli.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        _seed_event(connection)
        OutboxService(connection, max_attempts=1).process_once(
            publisher=lambda _event: (_ for _ in ()).throw(RuntimeError("offline")),
            worker_id="worker-cli",
        )
    finally:
        connection.close()

    listed = runner.invoke(app, ["outbox", "list", "--db", str(db_path), "--status", "dead_letter"])
    assert listed.exit_code == 0
    assert '"id": "evt-1"' in listed.output

    requeued = runner.invoke(app, ["outbox", "requeue", "evt-1", "--db", str(db_path)])
    assert requeued.exit_code == 0
    assert '"status": "requeued"' in requeued.output
