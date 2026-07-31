from __future__ import annotations

from decimal import Decimal
from importlib import import_module
from pathlib import Path

import pandas as pd
import pytest

from reconforge.audit import AuditLedgerError, append_audit_event, list_audit_events
from reconforge.config import ReconForgeConfig
from reconforge.db import connect, database_status, run_migrations
from reconforge.db.migrations import MIGRATIONS
from reconforge.platform.common import (
    PlatformError,
    date_diff_days,
    is_trusted_local_mode,
    require_permission,
    trusted_local_mode,
)
from reconforge.platform.matching import MatchingService
from reconforge.reconciliation.stock_gl import reconcile_stock_gl
from reconforge.utils.money import (
    InvalidAmountError,
    money_difference,
    round_money,
)

matching_module = import_module("reconforge.infrastructure.sqlite_matching")


def test_invalid_dates_are_exceptions_and_record_accounting_remains_balanced() -> None:
    stock = pd.DataFrame(
        [
            {
                "move_id": "MOVE-BAD-DATE",
                "date": "not-a-date",
                "source_document": "INV-1",
                "work_order": "WO-1",
                "total_cost": "10.00",
            }
        ],
    )
    gl = pd.DataFrame(
        [
            {
                "entry_id": "GL-1",
                "date": "2026-01-01",
                "reference": "INV-1",
                "work_order": "WO-1",
                "amount": "10.00",
            }
        ],
    )

    result = reconcile_stock_gl(stock, gl, ReconForgeConfig())

    assert result.matched_transactions.empty
    assert set(result.data_quality_exceptions["parse_error"]) == {"invalid_date"}
    assert result.invariants["record_accounting_ok"] is True
    assert result.invariants["accounted_stock_rows"] == 1
    assert result.invariants["accounted_gl_rows"] == 1


def test_missing_financial_values_and_dates_never_become_zero() -> None:
    with pytest.raises(InvalidAmountError):
        round_money(None)
    with pytest.raises(InvalidAmountError):
        money_difference(None, "1.00")
    assert date_diff_days("bad-date", "2026-01-01") is None


def test_unbound_actors_are_rejected_outside_trusted_local_mode(tmp_path: Path) -> None:
    db_path = tmp_path / "actor-context.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        assert is_trusted_local_mode() is True
        assert require_permission(connection, actor_label="local-cli", permission="accounts.prepare") is None
        with trusted_local_mode(False):
            assert is_trusted_local_mode() is False
            with pytest.raises(PlatformError, match="Authenticated actor required"):
                require_permission(connection, actor_label="local-cli", permission="accounts.prepare")
        assert is_trusted_local_mode() is True
    finally:
        connection.close()


def _write_match_inputs(tmp_path: Path) -> tuple[Path, Path]:
    left = tmp_path / "left.csv"
    right = tmp_path / "right.csv"
    left.write_text("id,reference,amount,date\nL-1,INV-1,10.00,2026-01-01\n", encoding="utf-8")
    right.write_text(
        "id,reference,amount,date\nR-1,INV-1,10.00,2026-01-01\nR-ORPHAN,OTHER,12.00,2026-01-01\n",
        encoding="utf-8",
    )
    return left, right


def test_platform_matching_persists_unmatched_right_records(tmp_path: Path) -> None:
    db_path = tmp_path / "matching.db"
    run_migrations(db_path)
    left, right = _write_match_inputs(tmp_path)
    connection = connect(db_path, require_exists=True)
    try:
        service = MatchingService(connection)
        result = service.run(left_path=left, right_path=right)
        rows = service.results(result.job_id)
        orphan = [row for row in rows if row["right_id"] == "R-ORPHAN"]
        assert len(orphan) == 1
        assert orphan[0]["left_id"] == ""
        assert orphan[0]["match_type"] == "unmatched_right"
    finally:
        connection.close()


def test_platform_matching_idempotency_reuses_job_and_outbox_event(tmp_path: Path) -> None:
    db_path = tmp_path / "idempotent.db"
    run_migrations(db_path)
    left, right = _write_match_inputs(tmp_path)
    connection = connect(db_path, require_exists=True)
    try:
        service = MatchingService(connection)
        first = service.run(left_path=left, right_path=right, idempotency_key="retry-1")
        second = service.run(left_path=left, right_path=right, idempotency_key="retry-1")
        assert second == first
        assert connection.execute("SELECT COUNT(*) AS count FROM match_jobs").fetchone()["count"] == 1
        assert connection.execute("SELECT COUNT(*) AS count FROM outbox_events").fetchone()["count"] == 1
    finally:
        connection.close()


def test_matching_failure_rolls_back_results_audit_and_outbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "atomic-matching.db"
    run_migrations(db_path)
    left, right = _write_match_inputs(tmp_path)
    connection = connect(db_path, require_exists=True)

    def fail_audit(*args: object, **kwargs: object) -> None:
        raise AuditLedgerError("forced audit failure")

    monkeypatch.setattr(matching_module, "audit", fail_audit)
    try:
        with pytest.raises(PlatformError, match="rolled back"):
            MatchingService(connection).run(left_path=left, right_path=right)
        assert connection.execute("SELECT COUNT(*) AS count FROM match_jobs").fetchone()["count"] == 0
        assert connection.execute("SELECT COUNT(*) AS count FROM match_results").fetchone()["count"] == 0
        assert connection.execute("SELECT COUNT(*) AS count FROM outbox_events").fetchone()["count"] == 0
        assert not list_audit_events(connection)
    finally:
        connection.close()


def test_audit_append_respects_an_existing_transaction(tmp_path: Path) -> None:
    db_path = tmp_path / "audit-transaction.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        connection.execute("BEGIN IMMEDIATE")
        append_audit_event(
            connection,
            actor_label="local-cli",
            object_type="test",
            object_id="TX-1",
            action="transaction_started",
        )
        assert connection.in_transaction
        connection.rollback()
        assert not list_audit_events(connection)
    finally:
        connection.close()


def test_outbox_is_a_formal_migration_and_legacy_upgrade_is_visible(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy-outbox.db"

    legacy = run_migrations(db_path, target_version=12)
    assert legacy.current_version == 12
    connection = connect(db_path, require_exists=True)
    try:
        assert (
            connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'outbox_events'",
            ).fetchone()
            is None
        )
    finally:
        connection.close()

    status = database_status(db_path)
    assert status.pending_versions == [migration.version for migration in MIGRATIONS if migration.version > 12]

    upgraded_to_outbox = run_migrations(db_path, target_version=13)
    assert upgraded_to_outbox.applied_versions == [13]
    connection = connect(db_path, require_exists=True)
    try:
        assert (
            connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'outbox_events'",
            ).fetchone()
            is not None
        )
        assert (
            connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'index' AND name = 'idx_outbox_events_pending'",
            ).fetchone()
            is not None
        )
    finally:
        connection.close()

    upgraded = run_migrations(db_path)
    assert upgraded.applied_versions == [migration.version for migration in MIGRATIONS if migration.version > 13]
    connection = connect(db_path, require_exists=True)
    try:
        delivery_columns = {
            str(row["name"]) for row in connection.execute("PRAGMA table_info(outbox_events)").fetchall()
        }
        assert {"available_at", "locked_at", "locked_by", "dead_lettered_at"} <= delivery_columns
    finally:
        connection.close()


# ---------------------------------------------------------------------------
# P0-004: Config amount_tolerance Decimal migration
# ---------------------------------------------------------------------------


def test_config_amount_tolerance_is_decimal() -> None:
    """Default config stores amount_tolerance as an exact Decimal."""
    config = ReconForgeConfig()
    assert isinstance(config.amount_tolerance, Decimal)


def test_config_amount_tolerance_rejects_binary_float_by_default() -> None:
    with pytest.raises(ValueError, match="strict-financial-input-v2"):
        ReconForgeConfig(amount_tolerance=2.0)


def test_config_amount_tolerance_accepts_string() -> None:
    config = ReconForgeConfig(amount_tolerance="0.01")
    assert config.amount_tolerance == Decimal("0.01")


def test_config_amount_tolerance_accepts_int_zero() -> None:
    config = ReconForgeConfig(amount_tolerance=0)
    assert config.amount_tolerance == Decimal("0")


def test_config_amount_tolerance_rejects_negative() -> None:
    with pytest.raises(ValueError):
        ReconForgeConfig(amount_tolerance=-1)


def test_config_amount_tolerance_rejects_nan() -> None:
    with pytest.raises(ValueError):
        ReconForgeConfig(amount_tolerance="nan")


def test_config_amount_tolerance_precision_edge_case_uses_exact_text() -> None:
    config = ReconForgeConfig(amount_tolerance="0.1")
    assert config.amount_tolerance == Decimal("0.1")


def test_config_amount_tolerance_serialization() -> None:
    """model_dump must produce a JSON-safe representation."""
    config = ReconForgeConfig(amount_tolerance="0.05")
    dumped = config.model_dump(mode="json")
    assert dumped["amount_tolerance"] == "0.05"


# ---------------------------------------------------------------------------
# P0-006 & P0-007: Stable Lineage IDs & Deterministic Order Invariance
# ---------------------------------------------------------------------------


def test_matching_engine_row_permutation_invariance() -> None:
    """Reconciling shuffled inputs must produce identical match pairs and match IDs."""
    stock = pd.DataFrame(
        [
            {
                "move_id": "MOVE-101",
                "date": "2026-01-05",
                "source_document": "INV-1001",
                "work_order": "WO-A",
                "total_cost": "500.00",
            },
            {
                "move_id": "MOVE-102",
                "date": "2026-01-06",
                "source_document": "INV-1002",
                "work_order": "WO-B",
                "total_cost": "750.50",
            },
            {
                "move_id": "MOVE-103",
                "date": "2026-01-07",
                "source_document": "INV-1003",
                "work_order": "WO-C",
                "total_cost": "1200.00",
            },
        ]
    )
    gl = pd.DataFrame(
        [
            {
                "entry_id": "GL-201",
                "date": "2026-01-05",
                "reference": "INV-1001",
                "work_order": "WO-A",
                "amount": "500.00",
            },
            {
                "entry_id": "GL-202",
                "date": "2026-01-06",
                "reference": "INV-1002",
                "work_order": "WO-B",
                "amount": "750.50",
            },
            {
                "entry_id": "GL-203",
                "date": "2026-01-07",
                "reference": "INV-1003",
                "work_order": "WO-C",
                "amount": "1200.00",
            },
        ]
    )

    config = ReconForgeConfig()
    res1 = reconcile_stock_gl(stock, gl, config)

    # Permute inputs completely
    stock_shuffled = stock.iloc[[2, 0, 1]].reset_index(drop=True)
    gl_shuffled = gl.iloc[[1, 2, 0]].reset_index(drop=True)
    res2 = reconcile_stock_gl(stock_shuffled, gl_shuffled, config)

    assert len(res1.matched_transactions) == len(res2.matched_transactions) == 3

    # Compare matched IDs and digests
    m1_pairs = set(
        zip(
            res1.matched_transactions["move_id"],
            res1.matched_transactions["entry_id"],
            res1.matched_transactions["match_id"],
            strict=True,
        )
    )
    m2_pairs = set(
        zip(
            res2.matched_transactions["move_id"],
            res2.matched_transactions["entry_id"],
            res2.matched_transactions["match_id"],
            strict=True,
        )
    )

    assert m1_pairs == m2_pairs, f"Permutation mismatch: {m1_pairs} vs {m2_pairs}"
    assert res1.invariants["record_accounting_ok"] is True
    assert res2.invariants["record_accounting_ok"] is True


def test_stable_match_id_format() -> None:
    """Match IDs must be SHA-256 derived hashes prefixed with MATCH-, independent of row index."""
    stock = pd.DataFrame(
        [
            {
                "move_id": "MOVE-X",
                "date": "2026-01-10",
                "source_document": "DOC-X",
                "work_order": "WO-X",
                "total_cost": "100.00",
            },
        ]
    )
    gl = pd.DataFrame(
        [
            {"entry_id": "GL-Y", "date": "2026-01-10", "reference": "DOC-X", "work_order": "WO-X", "amount": "100.00"},
        ]
    )

    res = reconcile_stock_gl(stock, gl, ReconForgeConfig())
    match_id = res.matched_transactions.iloc[0]["match_id"]
    assert match_id.startswith("MATCH-")
    assert len(match_id) == 26  # MATCH- (6) + 20 hex chars
