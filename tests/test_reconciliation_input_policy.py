from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest
from typer.testing import CliRunner

from reconforge.cli import app
from reconforge.config import ReconForgeConfig
from reconforge.db import connect, run_migrations
from reconforge.platform.common import PlatformError
from reconforge.platform.matching import MatchingService
from reconforge.reconciliation.stock_gl import reconcile_stock_gl
from reconforge.utils.money import (
    LEGACY_FINANCIAL_INPUT_POLICY,
    STRICT_FINANCIAL_INPUT_POLICY,
    InvalidAmountError,
    LegacyFinancialInputWarning,
    Money,
)


def _stock_gl_frames(amount: object) -> tuple[pd.DataFrame, pd.DataFrame]:
    stock = pd.DataFrame(
        [
            {
                "move_id": "SM-1",
                "date": "2026-07-25",
                "total_cost": amount,
                "source_document": "INV-1",
                "work_order": "WO-1",
                "currency": "USD",
            }
        ]
    )
    gl = pd.DataFrame(
        [
            {
                "entry_id": "GL-1",
                "date": "2026-07-25",
                "amount": amount,
                "reference": "INV-1",
                "work_order": "WO-1",
                "currency": "USD",
            }
        ]
    )
    return stock, gl


def _matching_records(amount: object) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    left = [{"id": "L-1", "amount": amount, "reference": "INV-1", "date": "2026-07-25"}]
    right = [{"id": "R-1", "amount": amount, "reference": "INV-1", "date": "2026-07-25"}]
    return left, right


def test_money_and_stock_gl_preserve_legacy_but_strictly_reject_binary_amounts() -> None:
    with pytest.warns(LegacyFinancialInputWarning, match="deprecated"):
        assert Money(10.5, "USD", input_policy=LEGACY_FINANCIAL_INPUT_POLICY).amount == Decimal("10.50")
    with pytest.raises(InvalidAmountError, match="strict-financial-input-v2"):
        Money(10.5, "USD", input_policy=STRICT_FINANCIAL_INPUT_POLICY)

    stock, gl = _stock_gl_frames(10.5)
    legacy = reconcile_stock_gl(
        stock,
        gl,
        ReconForgeConfig(),
        input_policy=LEGACY_FINANCIAL_INPUT_POLICY,
    )
    strict = reconcile_stock_gl(
        stock,
        gl,
        ReconForgeConfig(),
        input_policy=STRICT_FINANCIAL_INPUT_POLICY,
    )

    assert legacy.financial_input_policy == LEGACY_FINANCIAL_INPUT_POLICY
    assert len(legacy.matched_transactions) == 1
    assert strict.financial_input_policy == STRICT_FINANCIAL_INPUT_POLICY
    assert strict.matched_transactions.empty
    assert set(strict.data_quality_exceptions["source_dataset"]) == {"stock_moves", "gl_entries"}
    assert set(strict.data_quality_exceptions["parse_error"]) == {"invalid_amount"}
    assert set(strict.data_quality_exceptions["invalid_value"]) == {"10.5"}


def test_stock_gl_strict_policy_is_deterministic_for_exact_inputs() -> None:
    stock, gl = _stock_gl_frames("10.50")
    first = reconcile_stock_gl(
        stock,
        gl,
        ReconForgeConfig(),
        input_policy=STRICT_FINANCIAL_INPUT_POLICY,
    )
    second = reconcile_stock_gl(
        stock.iloc[::-1],
        gl.iloc[::-1],
        ReconForgeConfig(),
        input_policy=STRICT_FINANCIAL_INPUT_POLICY,
    )

    assert first.financial_input_policy == second.financial_input_policy == STRICT_FINANCIAL_INPUT_POLICY
    pd.testing.assert_frame_equal(first.matched_transactions, second.matched_transactions)
    pd.testing.assert_frame_equal(first.all_exceptions, second.all_exceptions)


def test_matching_service_policy_controls_data_quality_and_rejects_unknown_value(tmp_path: Path) -> None:
    db_path = tmp_path / "matching-policy.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        service = MatchingService(connection)
        left, right = _matching_records(10.5)
        legacy = service.match_records(
            left_records=left,
            right_records=right,
            financial_input_policy=LEGACY_FINANCIAL_INPUT_POLICY,
        )
        strict = service.match_records(
            left_records=left,
            right_records=right,
            financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
        )
        with pytest.raises(PlatformError, match="Unsupported financial input policy") as captured:
            service.match_records(
                left_records=left,
                right_records=right,
                financial_input_policy="secret-policy-value",  # type: ignore[arg-type]
            )
    finally:
        connection.close()

    assert legacy.financial_input_policy == LEGACY_FINANCIAL_INPUT_POLICY
    assert sum(item["status"] == "Matched" for item in legacy.results) == 1
    assert strict.financial_input_policy == STRICT_FINANCIAL_INPUT_POLICY
    assert not any(item["status"] == "Matched" for item in strict.results)
    assert {item["source_side"] for item in strict.exceptions} == {"Left", "Right"}
    assert {item["reason_code"] for item in strict.exceptions} == {"INVALID_AMOUNT"}
    assert "secret-policy-value" not in str(captured.value)


def test_matching_run_persists_policy_in_rule_audit_outbox_and_idempotency(tmp_path: Path) -> None:
    db_path = tmp_path / "matching-run-policy.db"
    left_path = tmp_path / "left.csv"
    right_path = tmp_path / "right.csv"
    left_path.write_text("id,amount,reference,date\nL-1,10.50,INV-1,2026-07-25\n", encoding="utf-8")
    right_path.write_text("id,amount,reference,date\nR-1,10.50,INV-1,2026-07-25\n", encoding="utf-8")
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        service = MatchingService(connection)
        first = service.run(
            left_path=left_path,
            right_path=right_path,
            idempotency_key="policy-run-1",
            financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
        )
        repeated = service.run(
            left_path=left_path,
            right_path=right_path,
            idempotency_key="policy-run-1",
            financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
        )
        rule = json.loads(
            connection.execute("SELECT rule_json FROM match_jobs WHERE id = ?", (first.job_id,)).fetchone()[
                "rule_json"
            ]
        )
        audit_metadata = json.loads(
            connection.execute(
                "SELECT metadata_json FROM audit_events WHERE object_id = ? AND action = 'match_job_completed'",
                (first.job_id,),
            ).fetchone()["metadata_json"]
        )
        outbox_payload = json.loads(
            connection.execute(
                "SELECT payload_json FROM outbox_events WHERE aggregate_id = ? AND event_type = 'match_job.completed'",
                (first.job_id,),
            ).fetchone()["payload_json"]
        )
        with pytest.raises(PlatformError, match="different financial input policy"):
            service.run(
                left_path=left_path,
                right_path=right_path,
                idempotency_key="policy-run-1",
                financial_input_policy=LEGACY_FINANCIAL_INPUT_POLICY,
            )
    finally:
        connection.close()

    assert first == repeated
    assert first.financial_input_policy == STRICT_FINANCIAL_INPUT_POLICY
    assert rule["financial_input_policy"] == STRICT_FINANCIAL_INPUT_POLICY
    assert audit_metadata["financial_input_policy"] == STRICT_FINANCIAL_INPUT_POLICY
    assert outbox_payload["financial_input_policy"] == STRICT_FINANCIAL_INPUT_POLICY


def test_cli_matching_writer_preserves_json_numeric_lexemes_under_strict_policy(tmp_path: Path) -> None:
    db_path = tmp_path / "cli-matching-policy.db"
    left_path = tmp_path / "left.json"
    right_path = tmp_path / "right.json"
    left_path.write_text(json.dumps(_matching_records(10.5)[0]), encoding="utf-8")
    right_path.write_text(json.dumps(_matching_records(10.5)[1]), encoding="utf-8")
    run_migrations(db_path)

    result = CliRunner().invoke(
        app,
        [
            "match",
            "run",
            "--left",
            str(left_path),
            "--right",
            str(right_path),
            "--db",
            str(db_path),
        ],
    )

    assert result.exit_code == 0, result.output
    connection = connect(db_path, require_exists=True)
    try:
        row = connection.execute("SELECT rule_json FROM match_jobs").fetchone()
        matched_count = connection.execute(
            "SELECT COUNT(*) AS count FROM match_results WHERE status = 'Matched'"
        ).fetchone()["count"]
    finally:
        connection.close()
    assert json.loads(row["rule_json"])["financial_input_policy"] == STRICT_FINANCIAL_INPUT_POLICY
    assert matched_count == 1
