"""Historical SQLite 53 fencing migration identity and rollback acceptance."""

from __future__ import annotations

import ast
from hashlib import sha256
from pathlib import Path

import pytest

from reconforge.db import connect, run_migrations
from reconforge.db.migration_53_outbox_fencing import (
    SQLITE_OUTBOX_FENCING_UPGRADE_SQL,
    atomic_outbox_fencing_upgrade,
)
from reconforge.platform.common import append_outbox_event

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "reconforge/db/migration_53_outbox_fencing.py"


def test_outbox_fencing_migration_is_frozen_and_has_no_runtime_schema_dependency() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    tree = ast.parse(source)
    assignments = {
        target.id: node.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    value = assignments.get("SQLITE_OUTBOX_FENCING_UPGRADE_SQL")
    assert isinstance(value, ast.Constant)
    assert isinstance(value.value, str)
    assert sha256(SQLITE_OUTBOX_FENCING_UPGRADE_SQL.encode("utf-8")).hexdigest() == (
        "7fdc58ad2783c41bedc5fecb4d8dfe4ed15f46171b5fee3c756d957b436850a6"
    )
    assert "outbox_fencing_schema" not in source


@pytest.mark.parametrize("failure_checkpoint", ["watermarked", "guards", "marked"])
def test_outbox_fencing_atomic_upgrade_rolls_back_every_schema_and_marker_change(
    tmp_path: Path, failure_checkpoint: str
) -> None:
    path = tmp_path / f"fencing-{failure_checkpoint}.db"
    run_migrations(path, target_version=52)
    with connect(path) as connection:
        append_outbox_event(
            connection,
            event_id="historical",
            event_type="test.created",
            aggregate_type="test",
            aggregate_id="historical",
            payload={"synthetic": True},
        )
        connection.commit()

        def fail(stage: str) -> None:
            if stage == failure_checkpoint:
                raise RuntimeError(f"synthetic failure after {stage}")

        with pytest.raises(RuntimeError, match=failure_checkpoint):
            atomic_outbox_fencing_upgrade(
                connection,
                schema_sql=SQLITE_OUTBOX_FENCING_UPGRADE_SQL,
                version=53,
                name="outbox_lease_fencing_and_delivery_evidence",
                applied_at="2026-10-03T00:00:00Z",
                checkpoint=fail,
            )
        assert {row["name"] for row in connection.execute("PRAGMA table_info(outbox_events)")} >= {
            "id",
            "attempts",
        }
        assert "lease_generation" not in {
            row["name"] for row in connection.execute("PRAGMA table_info(outbox_events)")
        }
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='outbox_delivery_evidence'"
        ).fetchone() is None
        assert connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 52
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 52
        assert connection.execute("SELECT COUNT(*) FROM outbox_events WHERE id='historical'").fetchone()[0] == 1


def test_outbox_fencing_migration_watermarks_history_and_keeps_new_events_at_zero_generation(tmp_path: Path) -> None:
    path = tmp_path / "fencing-success.db"
    run_migrations(path, target_version=52)
    with connect(path) as connection:
        append_outbox_event(
            connection,
            event_id="historical",
            event_type="test.created",
            aggregate_type="test",
            aggregate_id="historical",
            payload={"synthetic": True},
        )
        connection.commit()
    status = run_migrations(path, target_version=53)
    assert status.current_version == 53
    with connect(path) as connection:
        assert tuple(
            connection.execute(
                "SELECT lease_generation,lease_generation_floor FROM outbox_events WHERE id='historical'"
            ).fetchone()
        ) == (2, 2)
        append_outbox_event(
            connection,
            event_id="fresh",
            event_type="test.created",
            aggregate_type="test",
            aggregate_id="fresh",
            payload={"synthetic": True},
        )
        connection.commit()
        assert tuple(
            connection.execute(
                "SELECT lease_generation,lease_generation_floor FROM outbox_events WHERE id='fresh'"
            ).fetchone()
        ) == (0, 0)
