from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path
from typing import cast

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
    ManufacturingConservationRecord,
    ManufacturingControlError,
    MaterialIssue,
    ProductionCompletion,
    ProductionOrder,
    ScrapEvent,
    run_manufacturing_cost_control,
    verify_mass_and_cost_conservation,
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


def test_manufacturing_report_rejects_nested_decision_tampering_after_outer_rehash(tmp_path: Path) -> None:
    run = run_manufacturing_cost_control_files(
        ORDERS, ISSUES, COMPLETIONS, SCRAP, currency="EUR", tolerance="0.01", max_scrap_quantity="5"
    )
    output = tmp_path / "manufacturing-nested-tamper.json"
    write_manufacturing_report(run, output)
    payload = json.loads(output.read_text(encoding="utf-8"))
    payload["decisions"][0]["reason_codes"] = ["TAMPERED"]
    payload["artifact_digest"] = hashlib.sha256(
        json.dumps({key: value for key, value in payload.items() if key != "artifact_digest"}, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    ).hexdigest()
    output.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ManufacturingControlError, match="replay verification failed"):
        verify_manufacturing_report(output)


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


def test_mass_and_cost_conservation_exact_balance() -> None:
    # Inputs:
    # Material: 100,000 minor ($1000.00)
    # Labor:     50,000 minor ($500.00)
    # Overhead:  25,000 minor ($250.00)
    # Total Input Cost = 175,000 minor
    #
    # Outputs:
    # FG:       140,000 minor ($1400.00)
    # Scrap:     15,000 minor ($150.00)
    # WIP:       20,000 minor ($200.00)
    # Total Output Cost = 175,000 minor (Cost Leakage = 0)
    #
    # Mass:
    # Material Qty: 10,000 scaled units
    # FG Qty:        8,000 scaled units
    # Scrap Qty:     1,500 scaled units
    # WIP Qty:         500 scaled units
    # Total Output Mass = 10,000 (Mass Leakage = 0)

    record = ManufacturingConservationRecord(
        order_id="WO-CONSERVE-01",
        material_cost_minor=100_000,
        labor_cost_minor=50_000,
        overhead_cost_minor=25_000,
        finished_goods_cost_minor=140_000,
        scrap_cost_minor=15_000,
        remaining_wip_cost_minor=20_000,
        material_quantity_scaled=10_000,
        finished_goods_quantity_scaled=8_000,
        scrap_quantity_scaled=1_500,
        remaining_wip_quantity_scaled=500,
        currency="USD",
    )

    assert record.is_cost_conserved
    assert record.cost_leakage_minor == 0
    assert record.is_mass_conserved
    assert record.mass_leakage_scaled == 0

    # Formal invariant check passes without exception
    verify_mass_and_cost_conservation(record)


def test_cost_leakage_detection() -> None:
    # Cost leakage: Input cost 175,000 != Output cost 174,999 (leakage = +1 minor unit)
    record = ManufacturingConservationRecord(
        order_id="WO-LEAK-COST",
        material_cost_minor=100_000,
        labor_cost_minor=50_000,
        overhead_cost_minor=25_000,
        finished_goods_cost_minor=140_000,
        scrap_cost_minor=15_000,
        remaining_wip_cost_minor=19_999,  # 1 minor unit missing!
        material_quantity_scaled=10_000,
        finished_goods_quantity_scaled=8_000,
        scrap_quantity_scaled=1_500,
        remaining_wip_quantity_scaled=500,
        currency="USD",
    )

    assert not record.is_cost_conserved
    assert record.cost_leakage_minor == 1
    assert record.is_mass_conserved

    with pytest.raises(ManufacturingControlError, match="Manufacturing cost conservation violation"):
        verify_mass_and_cost_conservation(record)


def test_mass_leakage_detection() -> None:
    # Mass leakage: Input mass 10,000 != Output mass 9,990 (leakage = +10 scaled units)
    record = ManufacturingConservationRecord(
        order_id="WO-LEAK-MASS",
        material_cost_minor=100_000,
        labor_cost_minor=50_000,
        overhead_cost_minor=25_000,
        finished_goods_cost_minor=140_000,
        scrap_cost_minor=15_000,
        remaining_wip_cost_minor=20_000,
        material_quantity_scaled=10_000,
        finished_goods_quantity_scaled=8_000,
        scrap_quantity_scaled=1_500,
        remaining_wip_quantity_scaled=490,  # 10 units missing!
        currency="EUR",
    )

    assert record.is_cost_conserved
    assert not record.is_mass_conserved
    assert record.mass_leakage_scaled == 10

    with pytest.raises(ManufacturingControlError, match="Manufacturing mass conservation violation"):
        verify_mass_and_cost_conservation(record)


def test_conservation_record_type_and_value_invariants() -> None:
    # Float rejection in cost field
    with pytest.raises(ManufacturingControlError, match="material_cost_minor must be an exact non-negative integer"):
        ManufacturingConservationRecord(
            order_id="WO-ERR-FLOAT",
            material_cost_minor=cast(int, 1000.50),
            labor_cost_minor=0,
            overhead_cost_minor=0,
            finished_goods_cost_minor=0,
            scrap_cost_minor=0,
            remaining_wip_cost_minor=0,
            material_quantity_scaled=0,
            finished_goods_quantity_scaled=0,
            scrap_quantity_scaled=0,
            remaining_wip_quantity_scaled=0,
        )

    # Boolean rejection (which is a subclass of int in Python)
    with pytest.raises(ManufacturingControlError, match="must be an exact non-negative integer"):
        ManufacturingConservationRecord(
            order_id="WO-ERR-BOOL",
            material_cost_minor=cast(int, True),
            labor_cost_minor=0,
            overhead_cost_minor=0,
            finished_goods_cost_minor=0,
            scrap_cost_minor=0,
            remaining_wip_cost_minor=0,
            material_quantity_scaled=0,
            finished_goods_quantity_scaled=0,
            scrap_quantity_scaled=0,
            remaining_wip_quantity_scaled=0,
        )

    # Negative integer rejection
    with pytest.raises(ManufacturingControlError, match="must be an exact non-negative integer"):
        ManufacturingConservationRecord(
            order_id="WO-ERR-NEG",
            material_cost_minor=-100,
            labor_cost_minor=0,
            overhead_cost_minor=0,
            finished_goods_cost_minor=0,
            scrap_cost_minor=0,
            remaining_wip_cost_minor=0,
            material_quantity_scaled=0,
            finished_goods_quantity_scaled=0,
            scrap_quantity_scaled=0,
            remaining_wip_quantity_scaled=0,
        )
