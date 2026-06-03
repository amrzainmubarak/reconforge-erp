from __future__ import annotations

import hashlib
import json
from pathlib import Path

from reconforge.evidence.binder import generate_evidence_binder
from reconforge.evidence.index import write_evidence_index_html
from reconforge.evidence.models import EvidenceCase
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


def test_evidence_integrity_manifest_hashes_generated_files(tmp_path: Path, sample_datasets: dict[DatasetName, object]) -> None:
    output = _write_reconciliation_outputs(tmp_path / "output", sample_datasets)
    generate_evidence_binder(output, tmp_path / "evidence")
    manifest_path = tmp_path / "evidence" / "evidence_manifest.json"

    assert manifest_path.exists()
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["integrity_model"].startswith("SHA-256")
    manifest_entries = {entry["path"]: entry for entry in payload["files"]}
    assert "evidence_manifest.json" not in manifest_entries
    index_entry = manifest_entries["index.html"]
    digest = hashlib.sha256((tmp_path / "evidence" / "index.html").read_bytes()).hexdigest()
    assert index_entry["sha256"] == digest


def test_evidence_index_url_quotes_case_links(tmp_path: Path) -> None:
    path = write_evidence_index_html(
        [
            EvidenceCase(
                exception_id="EXC & 001",
                exception_type="stock_without_gl",
                severity="High",
                risk_score=80,
                business_impact="Review needed.",
                recommended_action="Check source records.",
                responsible_department="Finance",
            ),
        ],
        tmp_path,
    )
    html = path.read_text(encoding="utf-8")
    assert "href='EXC%20%26%20001/summary.md'" in html
    assert "EXC &amp; 001" in html
