from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest
from pydantic import ValidationError

from reconforge.evidence.binder import collect_evidence_cases, generate_evidence_binder
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


@pytest.mark.parametrize(
    ("risk_score", "status"),
    [(101, "valid"), (-1, "valid"), (None, "valid"), (0, "invalid"), (80.5, "valid")],
)
def test_evidence_case_enforces_risk_score_policy(risk_score: object, status: str) -> None:
    with pytest.raises(ValidationError, match="risk_score"):
        EvidenceCase(
            exception_id="EXC-POLICY",
            exception_type="data_quality",
            severity="Data Quality",
            risk_score=risk_score,  # type: ignore[arg-type]
            risk_score_status=status,  # type: ignore[arg-type]
            business_impact="Review needed.",
            recommended_action="Check source records.",
            responsible_department="Finance",
        )


def test_collect_evidence_cases_returns_empty_list_without_candidate_files(tmp_path: Path) -> None:
    assert collect_evidence_cases(tmp_path) == []


def test_generate_evidence_binder_handles_empty_candidate_inputs(tmp_path: Path) -> None:
    artifacts = generate_evidence_binder(tmp_path, tmp_path / "evidence")
    assert artifacts == []
    assert (tmp_path / "evidence" / "index.html").exists()
    assert (tmp_path / "evidence" / "evidence_register.xlsx").exists()


def test_evidence_binder_keeps_invalid_risk_scores_visible_without_zeroing(tmp_path: Path) -> None:
    pd.DataFrame(
        [
            {"exception_type": "exact_high", "risk_score": "61.000000000000000000", "risk_level": "Low"},
            {"exception_type": "malformed", "risk_score": "not-a-score", "risk_level": "Low"},
            {"exception_type": "fractional", "risk_score": "60.999999999999999999", "risk_level": "Low"},
            {"exception_type": "scientific", "risk_score": "6.1e1", "risk_level": "Low"},
            {"exception_type": "missing_high", "risk_score": "", "risk_level": "High"},
            {"exception_type": "missing_low", "risk_score": "", "risk_level": "Low"},
        ],
    ).to_csv(tmp_path / "stock_gl_all_exceptions.csv", index=False)

    cases = collect_evidence_cases(tmp_path)
    by_type = {case.exception_type: case for case in cases}

    assert set(by_type) == {"exact_high", "malformed", "fractional", "scientific", "missing_high"}
    assert by_type["exact_high"].risk_score == 61
    assert by_type["exact_high"].risk_score_status == "valid"
    for key in ("malformed", "fractional", "scientific"):
        assert by_type[key].risk_score is None
        assert by_type[key].risk_score_status == "invalid"
        assert by_type[key].severity == "Data Quality"
    assert by_type["missing_high"].risk_score is None
    assert by_type["missing_high"].risk_score_status == "missing"

    generate_evidence_binder(tmp_path, tmp_path / "evidence")
    payload = json.loads((tmp_path / "evidence" / "evidence_index.json").read_text(encoding="utf-8"))
    assert payload["schema_version"] == 3
    assert payload["financial_input_policy"] == "strict-financial-input-v2"
    assert payload["risk_score_policy"] == "integer-0-to-100-v1"
    malformed = next(case for case in payload["cases"] if case["exception_type"] == "malformed")
    assert malformed["risk_score"] is None
    assert malformed["risk_score_status"] == "invalid"
    summary = (tmp_path / "evidence" / "EXC-0002" / "summary.md").read_text(encoding="utf-8")
    assert "Unavailable (invalid)" in summary
