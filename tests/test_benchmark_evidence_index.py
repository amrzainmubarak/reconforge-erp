from __future__ import annotations

import hashlib
import json
import math
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
    assert len(report["verified_entries"]) == 20
    assert {entry["status"] for entry in report["verified_entries"]} == {"verified", "partial"}
    assert all(entry["digests"] for entry in report["verified_entries"])


def test_benchmark_evidence_publication_preserves_all_fifteen_accepted_entries() -> None:
    entries = json.loads(INDEX.read_text(encoding="utf-8"))["entries"]
    retained_bytes = json.dumps(entries[:15], sort_keys=True, separators=(",", ":")).encode("utf-8")
    assert hashlib.sha256(retained_bytes).hexdigest() == (
        "8449868b8a04b699602ce9223c773190feeccf20e115ec9e74a7af0bb3cfa829"
    )


def _retained_report(packet: dict[str, object]) -> dict[str, object]:
    """Reconstruct original report bytes without executing a benchmark."""
    serialization = packet["original_report_serialization"]
    assert isinstance(serialization, dict)
    assert serialization["encoding"] == "utf-8"
    assert serialization["final_newline"] is True
    measurement = packet["measurement"]
    assert isinstance(measurement, dict)
    text = json.dumps(
        measurement,
        indent=serialization["indent"],
        ensure_ascii=serialization["ensure_ascii"],
    ) + "\n"
    if serialization["line_endings"] == "CRLF":
        text = text.replace("\n", "\r\n")
    else:
        assert serialization["line_endings"] == "LF"
    assert hashlib.sha256(text.encode("utf-8")).hexdigest() == packet["original_report_sha256"]
    return measurement


def test_dimensional_snapshot_packet_preserves_raw_success_failure_and_independent_oracle() -> None:
    packet = json.loads((INDEX.parent / "native-dimensional-snapshot-1000-wave3-2026-10-10.json").read_text(encoding="utf-8"))
    report = _retained_report(packet)
    failed = _retained_report({"measurement": packet["failed_attempt"],
        "original_report_serialization": packet["failed_attempt_serialization"],
        "original_report_sha256": packet["failed_attempt_original_report_sha256"]})
    assert failed["status"] == "failed" and failed["owned_container_removed"] is True
    assert report["status"] == "passed" and report["source_unchanged"] is True
    assert report["owned_container_removed"] is True and report["runtime_role_flags"] == [False, False]
    assert report["source_commit"] == report["source_commit_after"] == "1319171964cbde85c1ec0be995d786a19fe02b20"
    assert report["source_sha256"] == report["source_sha256_after"] == packet["source_sha256"]
    assert report["posting"]["completed_cycles"] == 1  # This is not a1,000-posting throughput packet.
    comparison = report["snapshot_reads"]
    assert comparison["line_count"] == 1000 and comparison["expected_total_minor"] == "500"
    for name, count in (("per_line_baseline", 1002), ("joined_snapshot", 2)):
        assert len(comparison["samples"][name]) == 3
        for sample in comparison["samples"][name]:
            assert sample["status"] == "complete" and sample["client_execute_calls"] == count
            assert sample["lines"] == 1000 and sample["dimension_links"] == 668
            assert sample["debit_minor"] == sample["credit_minor"] == "500"
            assert sample["validation_digest"] == comparison["expected_validation_digest"] == packet["validation_digest"]
    assert comparison["median_seconds_baseline"] / comparison["median_seconds_optimized"] == comparison["measured_speedup"]


@pytest.mark.parametrize(
    ("filename", "commit", "source_digest", "raw_digest"),
    [
        (
            "enterprise-native-finance-pr127-34b9-2026-10-10.json",
            "34b9e7a5b2a7c4d8ae49b641a36de030a878d507",
            "6bd8978481a91491a635042f9d2603f32051976640213944f63562de106d5d57",
            "b051654acdae6c9878ca355a26b681519e37cd3ec59994583f317e514c71079f",
        ),
        (
            "enterprise-native-finance-current-6272889d-2026-10-10.json",
            "6272889d6ded2e20d4a52a79df234dd832ca6504",
            "8a0589ea12f4c860b3c507375c3cbb9c1ce42a55393b9e0e341922b3837d0e07",
            "5ec2b6adfd87a207bd7b55f557f391897cbfe0799616b63e8548b442453cebaf",
        ),
        (
            "enterprise-native-finance-post-repair-cfd30de7-2026-10-10.json",
            "cfd30de7a5ae1958b17e81f4988cbe9fa461457a",
            "4eb38a271b4b49b9d420c79b11513fb36b3d199697adfc31af26aa7fd9e05231",
            "306ab7117fca913ab81a367eba551634ae99b40a5bb62f18342a95a8be6994a4",
        ),
    ],
)
def test_retained_native_finance_reports_bind_source_and_independent_money_oracle(
    filename: str, commit: str, source_digest: str, raw_digest: str,
) -> None:
    packet = json.loads((INDEX.parent / filename).read_text(encoding="utf-8"))
    measurement = _retained_report(packet)

    assert packet["original_report_sha256"] == raw_digest
    assert packet["source_sha256"] == source_digest
    assert measurement["source_commit"] == measurement["source_commit_after"] == commit
    assert measurement["source_sha256"] == measurement["source_sha256_after"] == source_digest
    assert measurement["status"] == "passed"
    assert measurement["source_unchanged"] is True
    assert measurement["owned_container_removed"] is True
    assert measurement["runtime_role_flags"] == [False, False]
    assert measurement["profile"] == "native-three-human-cash-equity-v1"
    assert measurement["seed"] == "enterprise-native-v1"
    assert measurement["counts"] == [100, 1000]
    assert measurement["workers"] == 4
    assert measurement["repetitions"] == 3
    assert measurement["cost_per_transaction"] is None
    assert measurement["posting"]["completed_cycles"] == 1000
    assert measurement["posting"]["error_count"] == 0

    # Independently retained golden totals: do not import amount_minor,
    # expected_totals or the financial verifier to derive our expectation.
    golden_totals = {100: "46669102", 1000: "493671004"}
    assert measurement["posting"]["expected"] == {
        field: golden_totals[1000]
        for field in ("debit_minor", "credit_minor", "cash_minor", "equity_minor")
    }
    for profile in measurement["verified_reads"]:
        expected = golden_totals[profile["count"]]
        assert profile["expected"] == {
            field: expected
            for field in ("debit_minor", "credit_minor", "cash_minor", "equity_minor")
        }
        assert profile["cache_policy"] == "both warmed; alternating modes"
        for mode, samples in profile["samples"].items():
            assert [sample["repetition"] for sample in samples] == [0, 1, 2]
            for sample in samples:
                assert sample["effects"] == profile["count"]
                assert sample["error_count"] == 0
                assert sample["debit_minor"] == sample["credit_minor"] == expected
                assert sample["effects_digest"] == profile["financial_effects_digest"]
                assert sample["request_unit"] == (
                    "one_effect" if mode == "per_effect_baseline" else "up_to_100_effects"
                )
        if profile["count"] == 1000:
            assert profile["financial_effects_digest"] == packet["financial_effects_digest"]


def test_current_native_report_retains_complete_raw_vectors_and_sampled_resource_scope() -> None:
    packet = json.loads(
        (INDEX.parent / "enterprise-native-finance-current-6272889d-2026-10-10.json")
        .read_text(encoding="utf-8")
    )
    measurement = _retained_report(packet)
    posting = measurement["posting"]
    assert posting["requested_cycles"] == posting["admitted_cycles"] == 1000
    assert posting["not_admitted_cycles"] == 0
    assert posting["failed_cycles"] == []
    assert posting["completed_indices"] == list(range(1000))
    assert len(set(posting["ordered_effect_ids"])) == 1000
    assert len(posting["raw_cycle_latency_seconds"]) == 1000
    assert all(math.isfinite(value) and value >= 0 for value in posting["raw_cycle_latency_seconds"])
    for profile in measurement["verified_reads"]:
        assert profile["status"] == "passed"
        for mode, samples in profile["samples"].items():
            for sample in samples:
                assert sample["status"] == "complete"
                assert sample["requested_effects"] == profile["count"]
                raw = sample["raw_request_latency_seconds"]
                assert len(raw) == (
                    profile["count"] if mode == "per_effect_baseline" else profile["count"] // 100
                )
                assert all(math.isfinite(value) and value >= 0 for value in raw)

    sampling = measurement["resource_sampling"]
    assert sampling["status"] == "complete"
    assert sampling["thread_still_running"] is False
    assert sampling["errors"] == []
    assert sampling["interval_seconds"] == 10
    assert len(sampling["raw_samples"]) == 79
    summary = packet["resource_summary"]
    assert summary["sample_count"] == 79
    assert summary["maximum_sampled_client_rss_bytes"] == 125726720
    assert summary["maximum_sampled_docker_memory_mib"] == 215.2
    assert summary["maximum_sampled_docker_cpu_percent"] == 287.62
    assert summary["maximum_sampled_wait_event_sessions"]["Lock"] == 2
    assert summary["wal_counter_first_to_last_deltas"]["wal_bytes"] == 19880776
    assert summary["database_counter_first_to_last_deltas"]["deadlocks"] == 0
    assert summary["track_io_timing"] == measurement["postgres_configuration"]["track_io_timing"] == "off"
    assert "do not prove zero I/O latency" in summary["io_timing_interpretation"]
    assert summary["cost_per_successful_transaction"] is None
    assert summary["failover_rpo_seconds"] is summary["failover_rto_seconds"] is None

    baseline_packet = json.loads(
        (INDEX.parent / "enterprise-native-finance-pr127-34b9-2026-10-10.json").read_text(encoding="utf-8")
    )
    baseline = _retained_report(baseline_packet)
    # The accepted schema-v1 run never retained these vectors or sampled resources.
    assert "raw_cycle_latency_seconds" not in baseline["posting"]
    assert "resource_sampling" not in baseline
    assert measurement["posting"]["native_postings_per_second"] < baseline["posting"]["native_postings_per_second"]


def test_post_repair_report_retains_complete_observations_and_disclosed_regression() -> None:
    packet = json.loads((INDEX.parent / "enterprise-native-finance-post-repair-cfd30de7-2026-10-10.json").read_text(encoding="utf-8"))
    measurement = _retained_report(packet)
    assert measurement["posting"]["completed_indices"] == list(range(1000))
    assert len(set(measurement["posting"]["ordered_effect_ids"])) == 1000
    assert len(measurement["posting"]["raw_cycle_latency_seconds"]) == 1000
    assert measurement["posting"]["not_admitted_cycles"] == 0
    assert measurement["posting"]["failed_cycles"] == []
    assert all(math.isfinite(value) and value >= 0 for value in measurement["posting"]["raw_cycle_latency_seconds"])
    for profile in measurement["verified_reads"]:
        for mode, samples in profile["samples"].items():
            for sample in samples:
                raw = sample["raw_request_latency_seconds"]
                assert len(raw) == (profile["count"] if mode == "per_effect_baseline" else profile["count"] // 100)
                assert all(math.isfinite(value) and value >= 0 for value in raw)
    sampling = measurement["resource_sampling"]
    assert sampling["status"] == "complete" and sampling["errors"] == []
    assert sampling["thread_still_running"] is False
    assert sampling["interval_seconds"] == 10 and len(sampling["raw_samples"]) == 93
    assert packet["resource_summary"]["sample_count"] == 93
    assert packet["resource_summary"]["database_counter_first_to_last_deltas"]["deadlocks"] == 0
    assert packet["resource_summary"]["cost_per_successful_transaction"] is None
    assert "Docker was restarted" in packet["comparison_scope"]


def test_retained_commercial_projection_reports_preserve_both_profiles_and_raw_plans() -> None:
    packet = json.loads(
        (INDEX.parent / "commercial-collection-projection-two-runs-2026-10-10.json")
        .read_text(encoding="utf-8")
    )
    assert len(packet["profiles"]) == 2
    assert [profile["original_report_sha256"] for profile in packet["profiles"]] == [
        "a49d43553dfb7a6432350cadbf43a2bf784fb4b54bbe47408a16ecdd59a622ed",
        "42c2e8fadcd9bcd906e5011f985c24a58b9f677f85a3e55bc7f21a07b935f4bc",
    ]
    for profile in packet["profiles"]:
        measurement = _retained_report(profile)
        assert measurement["dataset"] == {
            "lines": 1, "tranches": 1, "collection_plans": 1,
            "invoice_minor": "45000", "collection_minor": "10000",
        }
        assert measurement["projection_identical"] is measurement["financial_source_unchanged"] is True
        assert measurement["measurements"]["baseline"]["allocation_scan_loops"] == 3
        assert measurement["measurements"]["candidate"]["allocation_scan_loops"] == 1
        for group in measurement["measurements"].values():
            assert len(group["execution_ms"]) == len(group["planning_ms"]) == 25
            assert group["first_plan"]["Plan"]["Actual Rows"] == 1
            assert all(math.isfinite(value) and value >= 0 for value in group["execution_ms"])


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
