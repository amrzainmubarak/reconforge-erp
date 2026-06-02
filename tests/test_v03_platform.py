from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from reconforge.ai.summaries import explain_exception_file
from reconforge.anonymizer.engine import anonymize_directory
from reconforge.benchmark.runner import run_benchmark
from reconforge.config import ReconForgeConfig
from reconforge.evidence.binder import generate_evidence_binder
from reconforge.generator.synthetic import generate_synthetic_dataset
from reconforge.io.writers import write_report_frames
from reconforge.plugins.registry import get_connector, list_connectors
from reconforge.reconciliation.matching import match_stock_to_gl, normalize_reference, reference_similarity
from reconforge.reconciliation.stock_gl import reconcile_stock_gl
from reconforge.reconciliation.stock_gl import result_frames as stock_frames
from reconforge.reconciliation.workorders import reconcile_workorders
from reconforge.reconciliation.workorders import result_frames as wo_frames
from reconforge.risk.engine import assess_exception_risk
from reconforge.rules.explain import explain_rule
from reconforge.rules.loader import load_rule_pack
from reconforge.rules.models import Condition
from reconforge.rules.operators import evaluate_condition
from reconforge.rules.registry import list_operators
from reconforge.schemas import DatasetName


def test_duplicate_operator() -> None:
    frame = pd.DataFrame({"reference": ["A", "A", "B"]})
    assert evaluate_condition(frame.iloc[0], Condition(operator="duplicate", field="reference"), frame=frame)


def test_unique_operator() -> None:
    frame = pd.DataFrame({"reference": ["A", "A", "B"]})
    assert evaluate_condition(frame.iloc[2], Condition(operator="unique", field="reference"), frame=frame)


def test_cross_file_exists_operator() -> None:
    row = pd.Series({"work_order": "WO-1"})
    related = {"invoices.csv": pd.DataFrame({"work_order": ["WO-1"]})}
    condition = Condition(operator="cross_file_exists", source_key="work_order", target_file="invoices.csv", target_key="work_order")
    assert evaluate_condition(row, condition, related_frames=related)


def test_cross_file_missing_operator() -> None:
    row = pd.Series({"work_order": "WO-2"})
    related = {"invoices.csv": pd.DataFrame({"work_order": ["WO-1"]})}
    condition = Condition(operator="cross_file_missing", source_key="work_order", target_file="invoices.csv", target_key="work_order")
    assert evaluate_condition(row, condition, related_frames=related)


def test_variance_before_after_and_aging_operators() -> None:
    row = pd.Series({"a": 125, "b": 100, "start": "2025-01-01", "end": "2026-01-01"})
    assert evaluate_condition(row, Condition(operator="variance_above", field="a", other_field="b", threshold=20))
    assert evaluate_condition(row, Condition(operator="before_date", field="start", other_field="end"))
    assert evaluate_condition(row, Condition(operator="after_date", field="end", other_field="start"))
    assert evaluate_condition(row, Condition(operator="aging_bucket", field="start", bucket_days=90))


def test_sum_matches_operator() -> None:
    row = pd.Series({"work_order": "WO-1", "actual_cost": 150})
    related = {"stock_moves.csv": pd.DataFrame({"work_order": ["WO-1", "WO-1"], "total_cost": [50, 100]})}
    condition = Condition(
        operator="sum_matches",
        field="actual_cost",
        source_key="work_order",
        target_file="stock_moves.csv",
        target_key="work_order",
        aggregate_field="total_cost",
        tolerance=0,
    )
    assert evaluate_condition(row, condition, related_frames=related)


def test_rule_registry_lists_advanced_operator() -> None:
    assert "cross_file_missing" in {operator.name for operator in list_operators()}


def test_rule_explain_command_helper() -> None:
    explanation = explain_rule("control-packs/audit-basic", "AB-001")
    assert "AB-001" in explanation
    assert "Recommended action" in explanation


def test_all_control_packs_have_required_files() -> None:
    required = {"pack.yml", "rules.yml", "mapping.yml", "risk_model.yml", "README.md", "expected-exceptions.md", "sample-command.md"}
    for pack in Path("control-packs").iterdir():
        if pack.is_dir():
            assert required.issubset({path.name for path in pack.iterdir()})


def test_all_control_packs_load() -> None:
    for pack in Path("control-packs").iterdir():
        if pack.is_dir():
            assert load_rule_pack(pack).rules


def test_reference_normalization_and_similarity() -> None:
    assert normalize_reference("AUTO/STK-1001") == "AUTOSTK1001"
    assert reference_similarity("STK-1001", "AUTO/STK-1001") > 0.8


def test_matching_strategy_audit_safe(sample_datasets: dict[DatasetName, pd.DataFrame]) -> None:
    result = reconcile_stock_gl(
        sample_datasets[DatasetName.STOCK_MOVES],
        sample_datasets[DatasetName.GL_ENTRIES],
        ReconForgeConfig(),
        matching_strategy="audit-safe",
    )
    assert "confidence_score" in result.matched_transactions.columns
    assert "review_required" in result.matched_transactions.columns


def test_matching_rejects_unknown_strategy(sample_datasets: dict[DatasetName, pd.DataFrame]) -> None:
    with pytest.raises(ValueError):
        match_stock_to_gl(sample_datasets[DatasetName.STOCK_MOVES], sample_datasets[DatasetName.GL_ENTRIES], ReconForgeConfig(), strategy="wild")  # type: ignore[arg-type]


def _write_outputs(tmp_path: Path, sample_datasets: dict[DatasetName, pd.DataFrame]) -> Path:
    config = ReconForgeConfig()
    stock_result = reconcile_stock_gl(sample_datasets[DatasetName.STOCK_MOVES], sample_datasets[DatasetName.GL_ENTRIES], config)
    wo_result = reconcile_workorders(
        sample_datasets[DatasetName.STOCK_MOVES],
        sample_datasets[DatasetName.WORK_ORDERS],
        sample_datasets[DatasetName.PURCHASE_ORDERS],
        sample_datasets[DatasetName.OLD_PARTS_RETURNS],
        sample_datasets[DatasetName.INVOICES],
        config,
    )
    write_report_frames(stock_frames(stock_result), tmp_path, "stock_gl")
    write_report_frames(wo_frames(wo_result), tmp_path, "workorders")
    return tmp_path


def test_evidence_binder_writes_index_register_and_review_form(tmp_path: Path, sample_datasets: dict[DatasetName, pd.DataFrame]) -> None:
    output = _write_outputs(tmp_path / "output", sample_datasets)
    artifacts = generate_evidence_binder(output, tmp_path / "evidence")
    assert artifacts
    assert (tmp_path / "evidence" / "index.html").exists()
    assert (tmp_path / "evidence" / "evidence_register.xlsx").exists()
    assert (artifacts[0].folder / "review_form.md").exists()


def test_anonymizer_public_demo_profile_masks_amounts(tmp_path: Path) -> None:
    target = tmp_path / "anon"
    anonymize_directory(Path("examples/sample_data"), target, profile="public-demo", amount_noise_percent=5)
    original = pd.read_csv("examples/sample_data/stock_moves.csv", keep_default_na=False)
    masked = pd.read_csv(target / "stock_moves.csv", keep_default_na=False)
    assert masked["work_order"].iloc[0].startswith("WO-ANON")
    assert float(masked["total_cost"].iloc[0]) != float(original["total_cost"].iloc[0])


def test_synthetic_dealership_currency_and_benchmark_html(tmp_path: Path) -> None:
    target = tmp_path / "synthetic"
    generate_synthetic_dataset(40, target, industry="dealership", currency="SAR", seed=12)
    stock = pd.read_csv(target / "stock_moves.csv", keep_default_na=False)
    assert "SAR" in set(stock["currency"])
    run_benchmark(target, tmp_path / "benchmark", engine_name="pandas")
    assert (tmp_path / "benchmark" / "benchmark.html").exists()


def test_risk_engine_outputs_escalation_and_note() -> None:
    assessment = assess_exception_risk("cancelled_po_linkage", {"amount": 2000})
    assert assessment.score >= 81
    assert assessment.escalation_level
    assert "Reviewed" in assessment.suggested_audit_note


def test_offline_exception_explainer(tmp_path: Path) -> None:
    path = tmp_path / "exceptions.json"
    path.write_text(json.dumps({"exceptions": [{"exception_id": "EXC-1", "exception_type": "stock_without_gl", "risk_score": 75}]}), encoding="utf-8")
    assert "EXC-1" in explain_exception_file(path, "EXC-1")


def test_plugin_registry_and_generic_connector(tmp_path: Path) -> None:
    assert "generic_csv" in list_connectors()
    connector = get_connector("generic_csv")
    assert connector.validate_schema({}) == ["No CSV datasets found."]
    datasets = connector.load_data(Path("examples/sample_data"))
    paths = connector.export_results({"stock_moves": datasets["stock_moves"]}, tmp_path)
    assert paths[0].exists()


def test_docs_critical_files_exist() -> None:
    for path in [
        "docs/market-intelligence.md",
        "docs/category-strategy.md",
        "docs/risk-scoring.md",
        "docs/anonymization.md",
        "docs/synthetic-data.md",
        "docs/ai-assistant.md",
        "docs/plugin-development.md",
        "docs/security-model.md",
        "docs/data-privacy.md",
        "docs/releases/v0.3.0.md",
    ]:
        assert Path(path).exists()
