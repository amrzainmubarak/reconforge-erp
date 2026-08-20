from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from reconforge.rules.engine import RulePackExecution, run_rule_pack, write_rule_results
from reconforge.rules.loader import load_rule_pack
from reconforge.rules.models import Condition, RuleDefinition
from reconforge.rules.operators import evaluate_condition
from reconforge.utils.money import InvalidAmountError


def test_valid_rule_pack_loading() -> None:
    pack = load_rule_pack(Path("control-packs/audit-basic"))
    assert pack.metadata.pack_id == "audit-basic"
    assert len(pack.rules) >= 5


def test_direct_rule_pack_execution_rejects_unsupported_financial_policy() -> None:
    pack = load_rule_pack(Path("control-packs/audit-basic"))
    with pytest.raises(InvalidAmountError, match="unsupported financial input policy"):
        RulePackExecution(
            pack=pack,
            results=[],
            input_files=(),
            financial_input_policy="unknown-v9",  # type: ignore[arg-type]
            decision_digest="0" * 64,
            generated_at="2026-01-01T00:00:00Z",
        )


def test_invalid_rule_schema(tmp_path: Path) -> None:
    pack_dir = tmp_path / "bad-pack"
    pack_dir.mkdir()
    (pack_dir / "pack.yml").write_text(
        "pack_id: bad\nname: Bad\nversion: 0.1\ndescription: Bad pack\n",
        encoding="utf-8",
    )
    (pack_dir / "rules.yml").write_text("rules:\n  - rule_id: BAD\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_rule_pack(pack_dir)


def test_invalid_pack_error() -> None:
    with pytest.raises(FileNotFoundError):
        load_rule_pack(Path("control-packs/does-not-exist"))


def test_equals_operator() -> None:
    row = {"status": "Closed"}
    condition = Condition(operator="equals", field="status", value="Closed")
    assert evaluate_condition(row, condition) is True


def test_missing_operator() -> None:
    row = {"work_order": ""}
    condition = Condition(operator="missing", field="work_order")
    assert evaluate_condition(row, condition) is True


def test_amount_tolerance_operator() -> None:
    row = {"stock_amount": "100.0", "gl_amount": "101.5"}
    condition = Condition(
        operator="amount_within_tolerance",
        field="stock_amount",
        other_field="gl_amount",
        tolerance="2.0",
    )
    assert evaluate_condition(row, condition) is True


def test_date_tolerance_operator() -> None:
    row = {"stock_date": "2026-01-01", "gl_date": "2026-01-03"}
    condition = Condition(operator="date_within_days", field="stock_date", other_field="gl_date", days=3)
    assert evaluate_condition(row, condition) is True


def test_and_logic() -> None:
    row = {"movement_type": "ISSUE", "work_order": ""}
    condition = Condition(
        operator="and",
        conditions=[
            Condition(operator="equals", field="movement_type", value="ISSUE"),
            Condition(operator="missing", field="work_order"),
        ],
    )
    assert evaluate_condition(row, condition) is True


def test_or_logic() -> None:
    row = {"movement_type": "DIRECT_FIT"}
    condition = Condition(
        operator="or",
        conditions=[
            Condition(operator="equals", field="movement_type", value="ISSUE"),
            Condition(operator="equals", field="movement_type", value="DIRECT_FIT"),
        ],
    )
    assert evaluate_condition(row, condition) is True


def test_rule_execution_output(tmp_path: Path) -> None:
    results = run_rule_pack(Path("examples/sample_data"), Path("control-packs/audit-basic"))
    assert results
    paths = write_rule_results(results, tmp_path)
    assert (tmp_path / "rule_results.csv").exists()
    assert (tmp_path / "rule_results.json").exists()
    assert len(paths) == 2
    payload = json.loads((tmp_path / "rule_results.json").read_text(encoding="utf-8"))
    assert set(payload) == {"results"}


def test_rule_definition_rejects_non_csv_source() -> None:
    payload = {
        "rule_id": "BAD-001",
        "rule_name": "Bad",
        "severity": "low",
        "entity_type": "stock",
        "source_file": "stock_moves.xlsx",
        "condition": {"operator": "missing", "field": "work_order"},
        "message": "Bad",
        "recommended_action": "Fix",
        "risk_impact": 1,
    }
    with pytest.raises(ValueError):
        RuleDefinition.model_validate(payload)


def test_pack_yaml_files_are_valid() -> None:
    for path in Path("control-packs").glob("*/pack.yml"):
        assert yaml.safe_load(path.read_text(encoding="utf-8"))["pack_id"]
