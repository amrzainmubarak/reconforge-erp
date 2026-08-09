from __future__ import annotations

import json
from pathlib import Path

import pytest

from reconforge.benchmark.evidence_index import BenchmarkEvidenceIndexError, verify_benchmark_index

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "docs" / "execution" / "benchmarks" / "INDEX.v1.json"


def test_benchmark_evidence_index_verifies_checked_in_artifacts() -> None:
    report = verify_benchmark_index(INDEX)

    assert report["index_id"] == "benchmark-evidence-index-v1"
    assert len(report["verified_entries"]) == 5
    assert {entry["status"] for entry in report["verified_entries"]} == {"verified", "partial"}
    assert all(entry["digests"] for entry in report["verified_entries"])


def test_benchmark_evidence_index_rejects_tampered_hash(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact.json"
    artifact.write_text(json.dumps({"profile_id": "test", "manifest_digest": "0" * 64}), encoding="utf-8")
    index = tmp_path / "index.json"
    index.write_text(
        json.dumps(
            {
                "index_id": "benchmark-evidence-index-v1",
                "schema_version": 1,
                "claim_boundary": "synthetic observation only",
                "entries": [
                    {
                        "artifact": "artifact.json",
                        "artifact_sha256": "f" * 64,
                        "claim_boundary": "synthetic observation only",
                        "digest_fields": ["manifest_digest"],
                        "engine": "test",
                        "profile_id": "test",
                        "status": "observed",
                        "workload_family": "test"
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(BenchmarkEvidenceIndexError, match="hash mismatch"):
        verify_benchmark_index(index, project_root=tmp_path)


def test_benchmark_evidence_index_rejects_path_escape(tmp_path: Path) -> None:
    index = tmp_path / "index.json"
    index.write_text(
        json.dumps(
            {
                "index_id": "benchmark-evidence-index-v1",
                "schema_version": 1,
                "claim_boundary": "synthetic observation only",
                "entries": [
                    {
                        "artifact": "../outside.json",
                        "artifact_sha256": "0" * 64,
                        "claim_boundary": "synthetic observation only",
                        "digest_fields": ["manifest_digest"],
                        "engine": "test",
                        "profile_id": "test",
                        "status": "observed",
                        "workload_family": "test"
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(BenchmarkEvidenceIndexError, match="escapes"):
        verify_benchmark_index(index, project_root=tmp_path)


def test_benchmark_evidence_index_rejects_global_claim_language(tmp_path: Path) -> None:
    index = tmp_path / "index.json"
    index.write_text(
        json.dumps(
            {
                "index_id": "benchmark-evidence-index-v1",
                "schema_version": 1,
                "claim_boundary": "best globally",
                "entries": []
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(BenchmarkEvidenceIndexError, match="claim boundary"):
        verify_benchmark_index(index, project_root=tmp_path)
