from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from reconforge.benchmark.evidence_index import BenchmarkEvidenceIndexError, verify_benchmark_index

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "docs" / "execution" / "benchmarks" / "INDEX.v1.json"


def test_benchmark_evidence_index_verifies_checked_in_artifacts() -> None:
    report = verify_benchmark_index(INDEX)

    assert report["index_id"] == "benchmark-evidence-index-v1"
    assert len(report["verified_entries"]) == 14
    assert {entry["status"] for entry in report["verified_entries"]} == {"verified", "partial"}
    assert all(entry["digests"] for entry in report["verified_entries"])


def test_benchmark_evidence_index_keeps_domain_diverse_postgres_claim_bounded() -> None:
    report = verify_benchmark_index(INDEX)

    entry = next(
        item
        for item in report["verified_entries"]
        if item["profile_id"] == "postgres-grouped-matching/10k-domain-diverse-v1"
    )

    assert entry["status"] == "partial"
    assert entry["digests"] == {
        "effect_set_digest": "78168229e37a78bb859e664a75098890e0671f9a502c8f6f04c30380ee9b3681",
        "manifest_digest": "c4d3461885fd3626b66a787caf8b3800706d1505d84169375885cc001e4a133a",
    }


def test_benchmark_evidence_index_keeps_domain_diverse_worker_parity_bounded() -> None:
    report = verify_benchmark_index(INDEX)

    entry = next(
        item
        for item in report["verified_entries"]
        if item["profile_id"] == "postgres-worker-domain-diverse-parity-v1"
    )

    assert entry["status"] == "partial"
    assert entry["digests"] == {
        "profile_digest": "0b0e875542be3a3d6d56fc7c3bf03e74dae21868ea0b55c9071c867246a57feb",
    }


def test_benchmark_verifier_script_prefers_checked_out_source_tree() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / ".github" / "scripts" / "verify_benchmark_index.py"),
            "--root",
            str(ROOT),
            "--index",
            str(INDEX),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert '"verified_entries"' in result.stdout


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


def test_benchmark_evidence_index_hashes_json_with_canonical_lf_endings(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact.json"
    artifact.write_bytes(b'{"manifest_digest":"' + b"0" * 64 + b'","profile_id":"test"}\r\n')
    index = tmp_path / "index.json"
    canonical_sha = hashlib.sha256(artifact.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    index.write_text(
        json.dumps(
            {
                "index_id": "benchmark-evidence-index-v1",
                "schema_version": 1,
                "claim_boundary": "synthetic observation only",
                "entries": [
                    {
                        "artifact": "artifact.json",
                        "artifact_sha256": canonical_sha,
                        "claim_boundary": "synthetic observation only",
                        "digest_fields": ["manifest_digest"],
                        "engine": "test",
                        "profile_id": "test",
                        "status": "observed",
                        "workload_family": "test",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    report = verify_benchmark_index(index, project_root=tmp_path)

    assert report["verified_entries"][0]["artifact_sha256"] == canonical_sha


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
