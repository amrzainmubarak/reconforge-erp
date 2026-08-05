from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError
from typer.testing import CliRunner

from reconforge.application.retail_settlement import verify_retail_settlement_report, write_retail_settlement_report
from reconforge.cli import app
from reconforge.domain.retail_settlement import (
    RetailPosBatch,
    RetailProcessorSettlement,
    RetailSettlementError,
    run_retail_settlement,
)
from reconforge.rules.engine import execute_rule_pack
from reconforge.rules.loader import load_rule_pack
from reconforge.utils.money import Money

runner = CliRunner()


def _money(value: str) -> Money:
    return Money.from_exact(value, "USD")


def _pos(batch_id: str = "POS-1") -> RetailPosBatch:
    return RetailPosBatch(
        batch_id,
        "STORE-1",
        "2026-08-04",
        "USD",
        _money("100.00"),
        _money("5.00"),
        _money("20.00"),
        _money("0.00"),
        _money("0.00"),
        _money("0.00"),
        10,
        f"pos-source-{batch_id}",
    )


def _settlement(batch_id: str = "POS-1", settlement_id: str = "SET-1", net: str = "93.00") -> RetailProcessorSettlement:
    return RetailProcessorSettlement(
        settlement_id,
        batch_id,
        "STORE-1",
        "2026-08-05",
        "USD",
        _money("100.00"),
        _money("5.00"),
        _money("2.00"),
        _money("0.00"),
        _money(net),
        f"provider-{settlement_id}",
    )


def test_retail_settlement_is_exact_and_explainable() -> None:
    run = run_retail_settlement((_pos(),), (_settlement(),), tolerance=_money("0.01"))
    assert run.status_counts == {"matched": 1}
    decision = run.decisions[0]
    assert decision.reason_code == "POS_SETTLEMENT_RECONCILED"
    assert decision.net_variance is not None
    assert decision.net_variance.amount == Decimal("0.00")
    assert len(run.decision_digest) == 64


def test_retail_settlement_keeps_variance_and_unmatched_records_visible() -> None:
    run = run_retail_settlement(
        (_pos("POS-1"), _pos("POS-2")),
        (_settlement("POS-1", net="92.50"), _settlement("POS-3", "SET-3")),
        tolerance=_money("0.01"),
    )
    assert run.status_counts == {"exception": 1, "unmatched_pos": 1, "unmatched_settlement": 1}
    assert {item.reason_code for item in run.decisions} == {
        "POS_SETTLEMENT_VARIANCE_ABOVE_TOLERANCE",
        "POS_BATCH_HAS_NO_SETTLEMENT",
        "SETTLEMENT_HAS_NO_POS_BATCH",
    }


def test_retail_settlement_marks_multiple_provider_rows_ambiguous() -> None:
    run = run_retail_settlement(
        (_pos(),),
        (_settlement(), _settlement(settlement_id="SET-2")),
        tolerance=_money("0.01"),
    )
    assert run.status_counts == {"ambiguous": 1}
    assert run.decisions[0].settlement_ids == ("SET-1", "SET-2")


def test_retail_settlement_is_permutation_stable_and_rejects_duplicates() -> None:
    first = run_retail_settlement(
        (_pos("POS-1"), _pos("POS-2")),
        (_settlement("POS-2", "SET-2"), _settlement("POS-1", "SET-1")),
        tolerance=_money("0.01"),
    )
    second = run_retail_settlement(
        (_pos("POS-2"), _pos("POS-1")),
        (_settlement("POS-1", "SET-1"), _settlement("POS-2", "SET-2")),
        tolerance=_money("0.01"),
    )
    assert first.decision_digest == second.decision_digest
    with pytest.raises(RetailSettlementError, match="settlement IDs must be unique"):
        run_retail_settlement(
            (_pos(),),
            (_settlement(), _settlement(settlement_id="SET-1")),
            tolerance=_money("0.01"),
        )


def test_retail_settlement_rejects_binary_float_and_currency_mismatch() -> None:
    with pytest.raises(RetailSettlementError, match="Money"):
        RetailPosBatch(
            "POS-FLOAT",
            "STORE-1",
            "2026-08-04",
            "USD",
            1.0,  # type: ignore[arg-type]
            _money("0"),
            _money("0"),
            _money("0"),
            _money("0"),
            _money("0"),
            1,
            "source",
        )
    with pytest.raises(RetailSettlementError, match="one currency"):
        run_retail_settlement((_pos(),), (), tolerance=Money.from_exact("0.01", "EUR"))


def test_retail_settlement_report_is_digest_bound(tmp_path: Path) -> None:
    run = run_retail_settlement((_pos(),), (_settlement(),), tolerance=_money("0.01"))
    path = tmp_path / "report.json"
    write_retail_settlement_report(run, path)
    payload = verify_retail_settlement_report(path)
    assert payload["decision_digest"] == run.decision_digest
    path.write_text(path.read_text(encoding="utf-8").replace('"status": "matched"', '"status": "exception"'), encoding="utf-8")
    with pytest.raises(RetailSettlementError, match="digest verification failed"):
        verify_retail_settlement_report(path)


def test_retail_settlement_cli_and_fixture_are_replayable(tmp_path: Path) -> None:
    output = tmp_path / "retail-report.json"
    result = runner.invoke(
        app,
        [
            "retail",
            "settlement",
            "settlement-run",
            "--pos-input",
            "examples/retail_settlement/pos_batches.json",
            "--settlement-input",
            "examples/retail_settlement/settlements.json",
            "--output",
            str(output),
        ],
    )
    assert result.exit_code == 0, result.output
    payload = verify_retail_settlement_report(output)
    assert payload["status_counts"] == {"exception": 1, "matched": 1, "unmatched_pos": 1}


def test_retail_settlement_report_schema_is_closed(tmp_path: Path) -> None:
    run = run_retail_settlement((_pos(),), (_settlement(),), tolerance=_money("0.01"))
    path = tmp_path / "report.json"
    write_retail_settlement_report(run, path)
    report = json.loads(path.read_text(encoding="utf-8"))
    schema = json.loads(Path("docs/schemas/retail_settlement_report.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(report)
    report["unexpected"] = True
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(report)


def test_retail_control_pack_loads_and_finds_expected_exceptions() -> None:
    pack = load_rule_pack(Path("control-packs/retail-pos-settlement"))
    execution = execute_rule_pack(Path("examples/retail_settlement/csv"), Path("control-packs/retail-pos-settlement"))
    assert pack.metadata.pack_id == "retail-pos-settlement"
    assert {item.rule_id for item in execution.results} == {"RPS-001", "RPS-003"}
