from __future__ import annotations

import json
from pathlib import Path

from reconforge.evidence.binder import generate_evidence_binder
from reconforge.io.writers import write_report_frames
from reconforge.reconciliation.stock_gl import reconcile_stock_gl
from reconforge.reconciliation.stock_gl import result_frames as stock_frames
from reconforge.reconciliation.workorders import reconcile_workorders
from reconforge.reconciliation.workorders import result_frames as wo_frames
from reconforge.schemas import DatasetName


def _write_reconciliation_outputs(tmp_path: Path, sample_datasets: dict[DatasetName, object]) -> Path:
    from reconforge.config import ReconForgeConfig

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


def test_evidence_binder_generation(tmp_path: Path, sample_datasets: dict[DatasetName, object]) -> None:
    output = _write_reconciliation_outputs(tmp_path / "output", sample_datasets)
    artifacts = generate_evidence_binder(output, tmp_path / "evidence")
    assert artifacts


def test_evidence_folder_structure(tmp_path: Path, sample_datasets: dict[DatasetName, object]) -> None:
    output = _write_reconciliation_outputs(tmp_path / "output", sample_datasets)
    artifacts = generate_evidence_binder(output, tmp_path / "evidence")
    first = artifacts[0].folder
    assert (first / "summary.md").exists()
    assert (first / "source_records.csv").exists()
    assert (first / "match_candidates.csv").exists()
    assert (first / "triggered_rules.yml").exists()
    assert (first / "recommended_action.md").exists()
    assert (first / "audit_trail.json").exists()


def test_evidence_summary_file_content(tmp_path: Path, sample_datasets: dict[DatasetName, object]) -> None:
    output = _write_reconciliation_outputs(tmp_path / "output", sample_datasets)
    artifact = generate_evidence_binder(output, tmp_path / "evidence")[0]
    content = (artifact.folder / "summary.md").read_text(encoding="utf-8")
    assert "Business Impact" in content
    assert "Audit Note Template" in content


def test_audit_trail_json_validity(tmp_path: Path, sample_datasets: dict[DatasetName, object]) -> None:
    output = _write_reconciliation_outputs(tmp_path / "output", sample_datasets)
    artifact = generate_evidence_binder(output, tmp_path / "evidence")[0]
    payload = json.loads((artifact.folder / "audit_trail.json").read_text(encoding="utf-8"))
    assert payload["exception_id"].startswith("EXC-")
