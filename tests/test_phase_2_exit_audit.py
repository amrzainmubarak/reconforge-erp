from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _load_yaml(relative: str) -> dict[str, Any]:
    value = yaml.safe_load((ROOT / relative).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_phase_two_exit_audit_matches_normative_matrix_and_completed_tasks() -> None:
    audit = _load_yaml("docs/execution/PHASE_2_EXIT_AUDIT.yaml")
    matrix = _load_yaml("docs/execution/PHASE_1_3_EXECUTION_MATRIX.yaml")
    backlog = _load_yaml("docs/execution/BACKLOG.yaml")
    phase = next(item for item in matrix["phases"] if item["id"] == "phase_2")
    tasks = {item["id"]: item for item in backlog["tasks"]}

    assert audit["status"] == "verified"
    assert audit["task_ids"] == phase["task_ids"]
    assert all(tasks[task_id]["status"] == "completed" for task_id in audit["task_ids"])
    assert {gate["id"] for gate in audit["gates"]} == {gate["id"] for gate in phase["required_gates"]}
    assert all(gate["status"] == "verified" and gate["evidence"] for gate in audit["gates"])


def test_phase_two_exit_audit_file_evidence_exists() -> None:
    audit = _load_yaml("docs/execution/PHASE_2_EXIT_AUDIT.yaml")
    paths = [item for gate in audit["gates"] for item in gate["evidence"] if "/" in item]
    assert paths
    assert all((ROOT / path).is_file() for path in paths)


def test_phase_two_benchmark_artifacts_are_hash_bound_and_hardware_scoped() -> None:
    suite_path = ROOT / "docs/execution/benchmarks/phase2/reconciliation-execution-benchmark-suite.json"
    suite = json.loads(suite_path.read_text(encoding="utf-8"))
    profiles = {item["profile_id"]: item for item in suite["profiles"]}
    signature_payload = {
        "profiles": [
            {
                "profile_id": profile["profile_id"],
                "result_signature": profile["result_signature"],
                "output_json_sha256": profile["output_json_sha256"],
            }
            for profile in suite["profiles"]
        ]
    }
    canonical_signature_payload = json.dumps(
        signature_payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    assert set(profiles) == {"10k", "100k"}
    assert hashlib.sha256(canonical_signature_payload).hexdigest() == suite["suite_signature"]
    assert profiles["10k"]["profile"]["total_records"] == 10_000
    assert profiles["100k"]["profile"]["total_records"] == 100_000
    for profile in profiles.values():
        relative = Path(profile["output_json"])
        assert not relative.is_absolute()
        assert ".." not in relative.parts
        assert "\\" not in profile["output_json"]
        payload = (suite_path.parent / relative).read_bytes()
        assert len(payload) == profile["output_json_bytes"]
        assert hashlib.sha256(payload).hexdigest() == profile["output_json_sha256"]
        assert profile["runtime_seconds"] > 0
        assert profile["cpu_time_seconds"] > 0
        assert profile["peak_memory_mb"] > 0
        assert profile["candidate_count_total"] >= profile["candidate_count_max"] > 0
        assert len(profile["result_signature"]) == 64
        assert profile["environment_metadata"]["cpu_count"] > 0
        assert profile["environment_metadata"]["python_version"]


def test_phase_two_exit_preserves_claim_boundaries() -> None:
    limitations = set(_load_yaml("docs/execution/PHASE_2_EXIT_AUDIT.yaml")["limitations"])
    assert {
        "benchmark_is_single_host_single_process",
        "no_1m_or_10m_claim",
        "no_database_or_distributed_throughput_claim",
        "no_production_readiness_claim",
        "no_external_assurance_claim",
    }.issubset(limitations)
