from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError
from typer.testing import CliRunner

from reconforge.application.manufacturing_cost_control import (
    run_manufacturing_cost_control_files,
    verify_manufacturing_report,
    write_manufacturing_report,
)
from reconforge.cli import app
from reconforge.domain.manufacturing_cost_control import (
    ManufacturingControlError,
    MaterialIssue,
    ProductionCompletion,
    ProductionOrder,
    ScrapEvent,
    run_manufacturing_cost_control,
)
from reconforge.utils.money import Money, Quantity

runner = CliRunner()
ROOT = Path("examples/manufacturing_cost_control")
ORDERS = ROOT / "orders.json"
ISSUES = ROOT / "issues.json"
COMPLETIONS = ROOT / "completions.json"
SCRAP = ROOT / "scrap.json"


def _money(value: str) -> Money:
    return Money.from_exact(value, "EUR")


def _quantity(value: str) -> Quantity:
    return Quantity(Decimal(value), "PCS")


def _order(order_id: str = "MFG-1", planned: str = "10", unit_cost: str = "2.00") -> ProductionOrder:
    return ProductionOrder(order_id, "PRODUCT-1", _quantity(planned), _money(unit_cost), "orders-1")


def _issue(issue_id: str = "ISSUE-1", order_id: str = "MFG-1", quantity: str = "10", unit_cost: str = "2.00") -> MaterialIssue:
    return MaterialIssue(issue_id, order_id, "RAW-1", _quantity(quantity), _money(unit_cost), "issues-1")


def _completion(completion_id: str = "COMP-1", order_id: str = "MFG-1", quantity: str = "10", cost: str = "20.00") -> ProductionCompletion:
    return ProductionCompletion(completion_id, order_id, "2026-08-05", _quantity(quantity), _money(cost), "completions-1")


def _scrap(scrap_id: str = "SCRAP-1", order_id: str = "MFG-1", quantity: str = "0") -> ScrapEvent:
    return ScrapEvent(scrap_id, order_id, "2026-08-05", _quantity(quantity), "setup", "scrap-1")


def test_fixture_control_keeps_reconciled_exception_and_unmatched_visible() -> None:
    run = run_manufacturing_cost_control_files(
        ORDERS, ISSUES, COMPLETIONS, SCRAP, currency="EUR", tolerance="0.01", max_scrap_quantity="5"
    )
    assert run.status_counts == {"exception": 1, "reconciled": 1, "unmatched": 1}
    mfg2 = next(item for item in run.decisions if item.order_id == "MFG-002")
    assert mfg2.reason_codes == (
        "MATERIAL_COST_VARIANCE",
        "COMPLETION_COST_RECONCILIATION_VARIANCE",
        "SCRAP_EXCEEDS_CONTROL_LIMIT",
    )
    assert len(run.decision_digest) == 64


def test_manufacturing_control_is_permutation_stable_and_exact() -> None:
    first = run_manufacturing_cost_control(
        (_order("MFG-2"), _order("MFG-1")),
        (_issue("ISSUE-2", "MFG-2"), _issue("ISSUE-1", "MFG-1")),
        (_completion("COMP-2", "MFG-2"), _completion("COMP-1", "MFG-1")),
        (_scrap("SCRAP-2", "MFG-2"), _scrap("SCRAP-1", "MFG-1")),
        amount_tolerance=_money("0.01"),
        max_scrap_quantity=_quantity("0"),
    )
    second = run_manufacturing_cost_control(
        (_order("MFG-1"), _order("MFG-2")),
        (_issue("ISSUE-1", "MFG-1"), _issue("ISSUE-2", "MFG-2")),
        (_completion("COMP-1", "MFG-1"), _completion("COMP-2", "MFG-2")),
        (_scrap("SCRAP-1", "MFG-1"), _scrap("SCRAP-2", "MFG-2")),
        amount_tolerance=_money("0.01"),
        max_scrap_quantity=_quantity("0"),
    )
    assert first.decision_digest == second.decision_digest
    assert all(item.status == "reconciled" for item in first.decisions)


def test_manufacturing_control_rejects_duplicates_units_floats_and_unknown_cost_currency() -> None:
    with pytest.raises(ManufacturingControlError, match="issue IDs must be unique"):
        run_manufacturing_cost_control(
            (_order(),), (_issue(), _issue()), (_completion(),), (_scrap(),), amount_tolerance=_money("0.01"), max_scrap_quantity=_quantity("0")
        )
    with pytest.raises(ManufacturingControlError, match="one unit"):
        run_manufacturing_cost_control(
            (_order(),), (_issue(),), (_completion(),), (_scrap(quantity="1"),), amount_tolerance=_money("0.01"), max_scrap_quantity=Quantity(Decimal("0"), "KG")
        )
    with pytest.raises(ManufacturingControlError, match="all manufacturing costs"):
        run_manufacturing_cost_control(
            (_order(),), (MaterialIssue("ISSUE-1", "MFG-1", "RAW-1", _quantity("1"), Money.from_exact("1", "USD"), "issues-1"),), (_completion(),), (_scrap(),), amount_tolerance=_money("0.01"), max_scrap_quantity=_quantity("0")
        )


def test_manufacturing_report_is_schema_and_digest_bound(tmp_path: Path) -> None:
    run = run_manufacturing_cost_control_files(
        ORDERS, ISSUES, COMPLETIONS, SCRAP, currency="EUR", tolerance="0.01", max_scrap_quantity="5"
    )
    output = tmp_path / "manufacturing-report.json"
    write_manufacturing_report(run, output)
    payload = verify_manufacturing_report(output)
    schema = json.loads(Path("docs/schemas/manufacturing_cost_control_report.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(payload)
    payload["tampered"] = True
    output.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ManufacturingControlError, match="digest verification failed"):
        verify_manufacturing_report(output)
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(payload)


def test_manufacturing_cli_writes_replayable_artifact(tmp_path: Path) -> None:
    output = tmp_path / "cli-report.json"
    result = runner.invoke(
        app,
        [
            "manufacturing", "cost-control", "run",
            "--orders-input", str(ORDERS), "--issues-input", str(ISSUES),
            "--completions-input", str(COMPLETIONS), "--scrap-input", str(SCRAP),
            "--currency", "EUR", "--max-scrap-quantity", "5", "--output", str(output),
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert verify_manufacturing_report(output)["status_counts"] == {"exception": 1, "reconciled": 1, "unmatched": 1}
