from __future__ import annotations

import json
from copy import deepcopy
from datetime import date
from decimal import Decimal, localcontext
from pathlib import Path

import pandas as pd
import pytest
from jsonschema import Draft202012Validator
from jsonschema import ValidationError as SchemaValidationError

from reconforge.config import ReconForgeConfig
from reconforge.io.writers import frame_to_records
from reconforge.reconciliation.stock_gl import StockGLReconciliationResult, reconcile_stock_gl
from reconforge.reconciliation.workorders import WorkorderReconciliationResult, reconcile_workorders
from reconforge.reports.html import write_html_dashboard
from reconforge.reports.management_pack import (
    _amount_impact_series,
    _executive_summary,
    _high_risk_exceptions,
    _management_pack_financial_input_issues,
    _risk_matrix,
    _to_decimal,
    generate_management_pack,
)
from reconforge.reports.markdown import write_markdown_summary
from reconforge.reports.wip_aging import generate_wip_aging
from reconforge.schemas import DatasetName
from reconforge.utils.money import LEGACY_FINANCIAL_INPUT_POLICY, CurrencyRegistry


def test_wip_aging_generates_90_plus_bucket(sample_datasets: dict[DatasetName, object], config: ReconForgeConfig) -> None:
    wip = generate_wip_aging(sample_datasets[DatasetName.WORK_ORDERS], config, as_of=date(2026, 6, 2))
    assert "90+" in set(wip["aging_bucket"])
    assert "WO-1005" in set(wip["work_order"])


def test_frame_to_records_serializes_dates(sample_datasets: dict[DatasetName, object]) -> None:
    records = frame_to_records(sample_datasets[DatasetName.WORK_ORDERS].head(1))
    assert isinstance(records[0]["opened_date"], str)


def test_markdown_summary_written(tmp_path: Path, sample_datasets: dict[DatasetName, object], config: ReconForgeConfig) -> None:
    stock_result = reconcile_stock_gl(sample_datasets[DatasetName.STOCK_MOVES], sample_datasets[DatasetName.GL_ENTRIES], config)
    wip = generate_wip_aging(sample_datasets[DatasetName.WORK_ORDERS], config, as_of=date(2026, 6, 2))
    path = write_markdown_summary(tmp_path / "summary.md", config, stock_result.summary, stock_result.summary, wip, 1)
    assert path.exists()
    assert "Executive Summary" in path.read_text(encoding="utf-8")


def test_html_dashboard_written(tmp_path: Path, sample_datasets: dict[DatasetName, object], config: ReconForgeConfig) -> None:
    stock_result = reconcile_stock_gl(sample_datasets[DatasetName.STOCK_MOVES], sample_datasets[DatasetName.GL_ENTRIES], config)
    wip = generate_wip_aging(sample_datasets[DatasetName.WORK_ORDERS], config, as_of=date(2026, 6, 2))
    path = write_html_dashboard(
        tmp_path / "dashboard.html",
        config,
        {"exception_count": 3},
        stock_result.all_exceptions,
        wip,
        control_value_summary=pd.DataFrame([{"metric": "total_exceptions", "value": 3}]),
    )
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "Top Exceptions" in text
    assert "Control Value Summary" in text


def test_management_pack_smoke(tmp_path: Path, sample_datasets: dict[DatasetName, object], config: ReconForgeConfig) -> None:
    stock_result = reconcile_stock_gl(sample_datasets[DatasetName.STOCK_MOVES], sample_datasets[DatasetName.GL_ENTRIES], config)
    workorder_result = reconcile_workorders(
        sample_datasets[DatasetName.STOCK_MOVES],
        sample_datasets[DatasetName.WORK_ORDERS],
        sample_datasets[DatasetName.PURCHASE_ORDERS],
        sample_datasets[DatasetName.OLD_PARTS_RETURNS],
        sample_datasets[DatasetName.INVOICES],
        config,
    )
    wip = generate_wip_aging(sample_datasets[DatasetName.WORK_ORDERS], config, as_of=date(2026, 6, 2))
    artifacts = generate_management_pack(Path("examples/sample_data"), tmp_path, config, stock_result, workorder_result, wip)
    assert artifacts.excel_path.exists()
    assert artifacts.json_path.exists()
    assert artifacts.markdown_path.exists()
    assert artifacts.html_path.exists()
    assert "Control Value Summary" in artifacts.html_path.read_text(encoding="utf-8")
    payload = json.loads(artifacts.json_path.read_text(encoding="utf-8"))
    schema = json.loads(Path("docs/schemas/management_pack.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    validator.validate(payload)
    version_three_payload = deepcopy(payload)
    version_three_payload["schema_version"] = 3
    version_three_payload.pop("matching_ambiguity_policy")
    validator.validate(version_three_payload)
    invalid_version_three = deepcopy(payload)
    invalid_version_three["schema_version"] = 3
    with pytest.raises(SchemaValidationError):
        validator.validate(invalid_version_three)
    version_two_payload = deepcopy(version_three_payload)
    version_two_payload["schema_version"] = 2
    version_two_payload.pop("record_identity_policy")
    validator.validate(version_two_payload)
    legacy_payload = deepcopy(payload)
    legacy_payload["schema_version"] = 1
    legacy_payload.pop("financial_input_policy")
    legacy_payload.pop("record_identity_policy")
    legacy_payload.pop("matching_ambiguity_policy")
    validator.validate(legacy_payload)
    assert payload["schema_version"] == 4
    assert payload["financial_input_policy"] == "strict-financial-input-v2"
    assert payload["record_identity_policy"] == "canonical-multiset-occurrence-v1"
    assert payload["matching_ambiguity_policy"] == "stable-tie-break-v1"
    metrics = {row["metric"] for row in payload["control_value_summary"]}
    assert "unresolved_high_risk_count" in metrics
    assert "recurring_exception_count" in metrics
    assert "close_checklist_completion_pct" in metrics
    assert "evidence_coverage_high_critical_pct" in metrics
    assert "unquantified_exception_count" in metrics
    assert "unquantified_wip_count" in metrics
    assert "data_quality_warnings" in payload
    assert "certification_metadata" in payload
    assert payload["currency_policy"]["currency"] == "USD"
    assert payload["currency_policy"]["currency_minor_units"] == 2
    assert payload["currency_policy"]["aggregation_policy"] == "single-currency-only-no-implicit-fx"
    assert set(stock_result.matched_transactions["currency"]) == {"USD"}


def test_management_pack_rejects_mixed_financial_input_policies(
    tmp_path: Path,
    sample_datasets: dict[DatasetName, object],
    config: ReconForgeConfig,
) -> None:
    stock_result = reconcile_stock_gl(
        sample_datasets[DatasetName.STOCK_MOVES],
        sample_datasets[DatasetName.GL_ENTRIES],
        config,
        input_policy=LEGACY_FINANCIAL_INPUT_POLICY,
    )
    workorder_result = reconcile_workorders(
        sample_datasets[DatasetName.STOCK_MOVES],
        sample_datasets[DatasetName.WORK_ORDERS],
        sample_datasets[DatasetName.PURCHASE_ORDERS],
        sample_datasets[DatasetName.OLD_PARTS_RETURNS],
        sample_datasets[DatasetName.INVOICES],
        config,
    )

    with pytest.raises(ValueError, match="one financial-input policy"):
        generate_management_pack(
            Path("examples/sample_data"),
            tmp_path / "mixed-policy-report",
            config,
            stock_result,
            workorder_result,
            pd.DataFrame(),
        )
    assert not (tmp_path / "mixed-policy-report").exists()


def test_management_pack_executive_summary_preserves_decimal_precision() -> None:
    stock_result = StockGLReconciliationResult(
        matched_transactions=pd.DataFrame({"stock_amount": [Decimal("0.10"), Decimal("0.20")]}),
        stock_without_gl=pd.DataFrame(),
        gl_without_stock=pd.DataFrame(),
        value_differences=pd.DataFrame(),
        date_differences=pd.DataFrame(),
        reference_mismatches=pd.DataFrame(),
        data_quality_exceptions=pd.DataFrame(),
        all_exceptions=pd.DataFrame(),
        summary=pd.DataFrame(),
        invariants={},
    )
    workorder_result = WorkorderReconciliationResult(
        parts_issued_without_work_order=pd.DataFrame(),
        closed_work_orders_with_pending_stock=pd.DataFrame(),
        work_orders_with_cost_but_no_invoice=pd.DataFrame(),
        direct_purchase_fitting_risk=pd.DataFrame(),
        old_part_return_missing=pd.DataFrame(),
        cancelled_po_linked_to_movement=pd.DataFrame(),
        all_exceptions=pd.DataFrame(),
        summary=pd.DataFrame(),
    )

    summary = _executive_summary(stock_result, workorder_result, pd.DataFrame())
    values = {str(row["metric"]): row["value"] for _, row in summary.iterrows()}
    assert values["matched_amount"] == Decimal("0.30")


def test_management_pack_summary_uses_currency_precision_under_hostile_decimal_context() -> None:
    stock_result = StockGLReconciliationResult(
        matched_transactions=pd.DataFrame(
            {
                "stock_amount": [Decimal("12345678901234567890.001"), Decimal("0.002")],
                "currency": ["KWD", "KWD"],
            },
        ),
        stock_without_gl=pd.DataFrame(),
        gl_without_stock=pd.DataFrame(),
        value_differences=pd.DataFrame(),
        date_differences=pd.DataFrame(),
        reference_mismatches=pd.DataFrame(),
        data_quality_exceptions=pd.DataFrame(),
        all_exceptions=pd.DataFrame(),
        summary=pd.DataFrame(),
        invariants={},
    )
    workorder_result = WorkorderReconciliationResult(
        parts_issued_without_work_order=pd.DataFrame(),
        closed_work_orders_with_pending_stock=pd.DataFrame(),
        work_orders_with_cost_but_no_invoice=pd.DataFrame(),
        direct_purchase_fitting_risk=pd.DataFrame(),
        old_part_return_missing=pd.DataFrame(),
        cancelled_po_linked_to_movement=pd.DataFrame(),
        all_exceptions=pd.DataFrame(),
        summary=pd.DataFrame(),
    )

    with localcontext() as context:
        context.prec = 4
        summary = _executive_summary(
            stock_result,
            workorder_result,
            pd.DataFrame(),
            currency_policy=CurrencyRegistry.resolve("KWD"),
        )

    matched = summary[summary["metric"].eq("matched_amount")].iloc[0]
    assert matched["value"] == Decimal("12345678901234567890.003")
    assert matched["currency"] == "KWD"
    assert matched["currency_minor_units"] == 3
    assert matched["currency_rounding_policy"] == "ROUND_HALF_UP"
    assert len(str(matched["currency_policy_digest"])) == 64


def test_management_pack_rejects_cross_currency_aggregation_before_writing(tmp_path: Path) -> None:
    stock_result = StockGLReconciliationResult(
        matched_transactions=pd.DataFrame(
            {
                "stock_amount": [Decimal("10.00"), Decimal("20.00")],
                "currency": ["USD", "EUR"],
            },
        ),
        stock_without_gl=pd.DataFrame(),
        gl_without_stock=pd.DataFrame(),
        value_differences=pd.DataFrame(),
        date_differences=pd.DataFrame(),
        reference_mismatches=pd.DataFrame(),
        data_quality_exceptions=pd.DataFrame(),
        all_exceptions=pd.DataFrame(),
        summary=pd.DataFrame(),
        invariants={},
    )
    workorder_result = WorkorderReconciliationResult(
        parts_issued_without_work_order=pd.DataFrame(),
        closed_work_orders_with_pending_stock=pd.DataFrame(),
        work_orders_with_cost_but_no_invoice=pd.DataFrame(),
        direct_purchase_fitting_risk=pd.DataFrame(),
        old_part_return_missing=pd.DataFrame(),
        cancelled_po_linked_to_movement=pd.DataFrame(),
        all_exceptions=pd.DataFrame(),
        summary=pd.DataFrame(),
    )
    output_dir = tmp_path / "mixed-currency-report"

    with pytest.raises(ValueError, match="without explicit FX conversion"):
        generate_management_pack(
            Path("examples/sample_data"),
            output_dir,
            ReconForgeConfig(output_currency="USD"),
            stock_result,
            workorder_result,
            pd.DataFrame(),
        )

    assert not output_dir.exists()


def test_high_risk_exceptions_respects_invalid_risk_score_values() -> None:
    exceptions = pd.DataFrame(
        [
            {"risk_score": "100"},
            {"risk_score": "bad"},
            {"risk_score": "61"},
            {"risk_score": Decimal("62")},
            {"risk_score": "60"},
        ],
    )
    high_risk = _high_risk_exceptions(exceptions)
    assert list(high_risk["risk_score"]) == ["100", "61", Decimal("62")]


def test_amount_impact_series_preserves_invalid_values_without_crashing() -> None:
    exceptions = pd.DataFrame(
        [
            {"amount_impact": "N/A", "actual_cost": "10.00"},
            {"amount_impact": "N/A", "total_cost": "abc"},
            {"amount_impact": "5", "actual_cost": "7.00"},
        ],
    )
    amounts = _amount_impact_series(exceptions)

    assert amounts.tolist()[0] == Decimal("10.00")
    assert amounts.tolist()[1] is None
    assert amounts.tolist()[2] == Decimal("5")


def test_management_pack_surfaces_invalid_optional_financial_values_without_raw_data() -> None:
    exceptions = pd.DataFrame(
        [
            {"risk_score": "not-a-score", "amount_impact": "not-an-amount"},
            {"risk_score": "61", "amount_impact": "10.00", "actual_cost": "bad"},
        ],
    )

    issues = _management_pack_financial_input_issues([("exceptions", exceptions)])

    assert len(issues) == 2
    assert {issue.column for issue in issues} == {"risk_score", "amount_impact|actual_cost"}
    assert all(issue.check == "financial_input_policy" for issue in issues)
    assert all("not-a-score" not in issue.message and "not-an-amount" not in issue.message for issue in issues)


def test_management_pack_does_not_report_invalid_fallback_when_an_amount_is_valid() -> None:
    exceptions = pd.DataFrame([{"amount_impact": "bad", "actual_cost": "10.00"}])

    assert _management_pack_financial_input_issues([("exceptions", exceptions)]) == []


def test_risk_matrix_ignores_invalid_amounts_when_summing() -> None:
    exceptions = pd.DataFrame(
        [
            {"exception_type": "inventory", "risk_level": "High", "amount": "bad"},
            {"exception_type": "inventory", "risk_level": "High", "amount": "100.00"},
        ],
    )
    matrix = _risk_matrix(exceptions)

    assert len(matrix) == 1
    assert matrix.iloc[0]["amount_impact"] == Decimal("100.00")
    assert matrix.iloc[0]["unquantified_amount_count"] == 1


def test_to_decimal_rejects_invalid_amount_text() -> None:
    with pytest.raises(ValueError):
        _to_decimal("invalid-amount")

    with pytest.raises(ValueError):
        _to_decimal(None)


def test_management_pack_rejects_binary_float_financial_values() -> None:
    with pytest.raises(ValueError, match="Invalid amount value"):
        _to_decimal(0.1)
