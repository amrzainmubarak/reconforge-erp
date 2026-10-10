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
    assert len(report["verified_entries"]) == 22
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
# Append to tests/test_benchmark_evidence_index.py after publication completes.
# Reuses that module's ROOT, INDEX, _retained_report and standard imports.


def _wave3_sha256(value: object) -> None:
    assert isinstance(value, str) and len(value) == 64
    assert set(value) <= set("0123456789abcdef")


def _wave3_acceptance_packet() -> dict[str, object]:
    return json.loads((ROOT / "docs/execution/GLOBAL_INTEGRITY_ACCEPTANCE_2026-10-10.json").read_text(encoding="utf-8"))


def _wave3_normalized_arguments(report: dict[str, object]) -> list[str]:
    command = report["command"]
    assert isinstance(command, list) and len(command) >= 4
    values = iter(command[2:])  # Interpreter/script locations differ by worktree.
    normalized = []
    for value in values:
        if value == "--output":
            assert next(values, None)
            normalized.extend((value, "<retained-output>"))
        else:
            normalized.append(value)
    return normalized


def test_wave3_publication_preserves_all_twenty_predecessor_index_entries() -> None:
    entries = json.loads(INDEX.read_text(encoding="utf-8"))["entries"]
    assert len(entries) == 22
    retained_bytes = json.dumps(entries[:20], sort_keys=True, separators=(",", ":")).encode("utf-8")
    assert hashlib.sha256(retained_bytes).hexdigest() == "3f1ecffac62b7cc3cbea41264f2a61b7948d9875c87dd32f7eddf7f51238be41"
    assert [Path(row["artifact"]).name for row in entries[20:]] == [
        "enterprise-native-finance-wave3-baseline-806a05db-2026-10-10.json",
        "enterprise-native-finance-wave3-candidate-70dffef7-2026-10-10.json",
    ]


def test_wave3_quiet_pair_retains_exact_reports_equal_workload_and_independent_money() -> None:
    from pathlib import PureWindowsPath

    sources = (
        ("baseline", "806a05db8a6ad442f0c79170277ab209a0fe9049"),
        ("candidate", "70dffef7b04446d59de2ff35b39fce1933974aad"),
    )
    reports = []
    for label, commit in sources:
        name = f"enterprise-native-finance-wave3-{label}-{commit[:8]}-2026-10-10.json"
        packet = json.loads((INDEX.parent / name).read_text(encoding="utf-8"))
        report = _retained_report(packet)
        assert report["source_commit"] == report["source_commit_after"] == commit
        assert report["source_sha256"] == report["source_sha256_after"] == packet["source_sha256"]
        assert report["source_unchanged"] is report["owned_container_removed"] is True
        assert report["status"] == "passed" and report["runtime_role_flags"] == [False, False]
        assert report["profile"] == "native-three-human-cash-equity-v1"
        assert report["seed"] == "enterprise-native-v1"
        assert report["counts"] == [100, 1000] and report["workers"] == 4 and report["repetitions"] == 3
        # The instrumented predecessor predates the optional dimensional fixture.
        # Absence means that fixture was not requested; preserve the raw report.
        assert report.get("snapshot_lines", 0) == 0
        assert report["cost_per_transaction"] is None
        for origin in report["module_origins"].values():
            # Recorded Windows paths are evidence, not paths on the CI host.
            assert PureWindowsPath(origin).relative_to(PureWindowsPath(report["runtime_root"])).parts[0] == "reconforge"
        posting = report["posting"]
        assert posting["requested_cycles"] == posting["admitted_cycles"] == posting["completed_cycles"] == 1000
        assert posting["error_count"] == posting["not_admitted_cycles"] == 0
        assert posting["failed_cycles"] == [] and posting["completed_indices"] == list(range(1000))
        assert len(posting["ordered_effect_ids"]) == len(set(posting["ordered_effect_ids"])) == 1000
        assert len(posting["raw_cycle_latency_seconds"]) == 1000
        assert all(math.isfinite(value) and value >= 0 for value in posting["raw_cycle_latency_seconds"])
        # Independent literal goldens: no imports from the benchmark money helper.
        golden = {100: "46669102", 1000: "493671004"}
        assert posting["expected"] == {field: golden[1000] for field in ("debit_minor", "credit_minor", "cash_minor", "equity_minor")}
        assert [read["count"] for read in report["verified_reads"]] == [100, 1000]
        requests, samples = 0, 0
        for read in report["verified_reads"]:
            count, expected = read["count"], golden[read["count"]]
            assert read["status"] == "passed" and read["cache_policy"] == "both warmed; alternating modes"
            assert read["expected"] == {field: expected for field in ("debit_minor", "credit_minor", "cash_minor", "equity_minor")}
            assert set(read["samples"]) == {"per_effect_baseline", "bounded_batch"}
            for mode, observations in read["samples"].items():
                assert [sample["repetition"] for sample in observations] == [0, 1, 2]
                for sample in observations:
                    assert sample["status"] == "complete" and sample["error_count"] == 0
                    assert sample["requested_effects"] == sample["effects"] == count
                    assert sample["debit_minor"] == sample["credit_minor"] == expected
                    assert sample["effects_digest"] == read["financial_effects_digest"]
                    assert sample["request_unit"] == ("one_effect" if mode == "per_effect_baseline" else "up_to_100_effects")
                    raw = sample["raw_request_latency_seconds"]
                    assert len(raw) == (count if mode == "per_effect_baseline" else count // 100)
                    assert all(math.isfinite(value) and value >= 0 for value in raw)
                    requests += len(raw)
                    samples += 1
            if count == 1000:
                assert read["financial_effects_digest"] == packet["financial_effects_digest"]
        assert (requests, samples) == (3333, 12)
        sampling = report["resource_sampling"]
        assert sampling["status"] == "complete" and sampling["errors"] == []
        assert sampling["thread_still_running"] is False
        assert sampling["interval_seconds"] == 10 and sampling["raw_samples"]
        for key in ("source_sha256", "financial_effects_digest", "original_report_sha256"):
            _wave3_sha256(packet[key])
        reports.append(report)
    assert _wave3_normalized_arguments(reports[0]) == _wave3_normalized_arguments(reports[1])
    for key in ("schema_version", "profile", "seed", "counts", "workers", "repetitions", "max_seconds", "image",
                "python", "platform", "logical_cpus", "processor", "architecture", "docker_version", "docker_engine_resources",
                "postgres_version", "postgres_configuration", "telemetry_policy"):
        assert reports[0][key] == reports[1][key], key
    configuration = reports[0]["postgres_configuration"]
    assert configuration["fsync"] == configuration["full_page_writes"] == configuration["synchronous_commit"] == "on"
    assert configuration["wal_level"] == "replica"
    # Fresh databases have independent random native identities. Their effect
    # digests must match within each run, not across the two databases.


def _wave3_native_packet(packet: dict[str, object], source: str, digest: str, count: int) -> None:
    from xml.etree import ElementTree

    report = _retained_report(packet)
    assert report["source_commit"] == source
    assert report["source_sha256_before"] == report["source_sha256_after"] == digest
    assert report["source_unchanged"] is report["native_cases_passed"] is report["accepted"] is True
    assert report["tracked_status_before"] == report["tracked_status_after"] == ""
    assert report["pytest_exit_code"] == 0 and report["timed_out"] is False
    assert report["counts"] == {"tests": count, "failures": 0, "errors": 0, "skipped": 0}
    xml = packet["junit_xml"].encode("utf-8")  # Preserve retained CRLF, never read_text-normalize.
    assert hashlib.sha256(xml).hexdigest() == packet["junit_sha256"]
    tree = ElementTree.fromstring(xml)
    cases = list(tree.iter("testcase"))
    assert len(cases) == count and all(case.attrib.get("name") for case in cases)
    assert not any(case.find(tag) is not None for case in cases for tag in ("failure", "error", "skipped"))
    for suite in tree.iter("testsuite"):
        assert int(suite.attrib.get("failures", "0")) == int(suite.attrib.get("errors", "0")) == int(suite.attrib.get("skipped", "0")) == 0
    _wave3_sha256(packet["diagnostic_log_sha256"])
    # This launcher emits its report before finally removes its container;
    # no invented cleanup field is required from that original native JSON.


def test_wave3_acceptance_retains_owner_and_asset_fix_sources_and_real_junit_cases() -> None:
    packet = _wave3_acceptance_packet()
    assert packet["schema_version"] == "global-integrity-local-acceptance-v1"
    assert packet["status"] == "scoped_local_gates_passed_hosted_acceptance_pending"
    assert packet["accepted_historical_base"] == "34b9e7a5b2a7c4d8ae49b641a36de030a878d507"
    assert packet["implementation_dependency"] == "6995141426fea1670b64313ae1a5b2f1d6064f8f"
    owner_source = "4bb4d1f94b99f5e9b90c3b489055ddba5172fe0a"
    asset_source = "70dffef7b04446d59de2ff35b39fce1933974aad"
    assert packet["integrated_owner_source"] == owner_source and packet["asset_lock_fix_source"] == asset_source
    gates = packet["native_owner_gates"]
    assert len(gates) == 3
    for gate, count in zip(gates, (19, 49, 23), strict=True):
        _wave3_native_packet(gate, owner_source, "0dfea2da8acb0ac52c5bfca46a2e69090cf36629724e2bf1ae5c5ba32b18a80a", count)
    _wave3_native_packet(packet["native_asset_lock_fix_gate"], asset_source, "4c68763b6abea5440564964848bab4de3299057ac4dbb9c3bfc7458897174918", 19)
    assert sum(gate["measurement"]["counts"]["tests"] for gate in gates) == 91
    assert any("overlap" in limit for limit in packet["limits"])
    assert len(packet["quality"]) == 3
    for quality in packet["quality"]:
        _retained_report(quality)  # Preserve every quality observation with its actual outcome.
    combined = packet["independent_combined_financial_oracle"]
    assert combined["synthetic"] is True and combined["branches"] == ["normal", "cancel_then_replace"]
    for name, expected in {"posted_effects": 18, "debit_minor": 184156, "credit_minor": 184156, "cash_minor": 45898,
                           "inventory_minor": 11648, "october_assets_minor": 66147, "january_assets_minor": 57546,
                           "capital_minor": 50000, "january_unclosed_result_minor": 7546}.items():
        assert combined[name] == expected


def test_wave3_three_real_https_cycles_retain_populated_restore_and_financial_goldens() -> None:
    packet = _wave3_acceptance_packet()
    wrappers = packet["real_https_and_populated_restore"]
    assert len(wrappers) == 3
    reports = {_retained_report(wrapper)["scenario"]: wrapper["measurement"] for wrapper in wrappers}
    assert set(reports) == {"collections", "landed-cost", "fixed-assets"}
    for scenario, report in reports.items():
        source = "70dffef7b04446d59de2ff35b39fce1933974aad" if scenario == "fixed-assets" else "4bb4d1f94b99f5e9b90c3b489055ddba5172fe0a"
        assert report["source_commit"] == report["source_commit_after"] == source
        assert report["status"] == "passed" and report["source_unchanged"] is True
        assert report["tracked_clean_before"] is report["tracked_clean_after"] is True
        assert report["tracked_status_before"] == report["tracked_status_after"] == ""
        assert report["built_web_unchanged"] is report["owned_https_process_stopped"] is report["owned_container_removed"] is True
        assert report["browser_exit_code"] == 0 and report["role_privileges"] == [False, False]
        assert report["revision"] == "0125_pg_landed_cost_cancellation"
        counts = report["browser_counts"]
        assert counts["expected"] == 1 and counts["skipped"] == counts["unexpected"] == counts["flaky"] == 0
        restore = report["native_restore"]
        assert restore["status"] == "passed" and restore["tamper_refusals"] == 3
        assert restore["verified_effects"] == report["persisted_effects"]
        _wave3_sha256(restore["dump_sha256"])
        snapshot, checkpoint = restore["snapshot"], restore["probe_checkpoint"]
        assert len(snapshot["tables"]) == len(checkpoint["tables"]) == 239
        assert snapshot["head"] == checkpoint["head"] == "0125_pg_landed_cost_cancellation"
        assert snapshot["objects"] == checkpoint["objects"]
        assert snapshot["objects"]["functions"]["count"] == 238
        assert snapshot["forced_rls_financial_tables"] == checkpoint["forced_rls_financial_tables"] == {"collections": 49, "landed-cost": 60, "fixed-assets": 45}[scenario]
        # Authenticated restore verification updates identity_users. Preserve its
        # two separate raw fingerprints; every other table remains exact.
        assert {name: value for name, value in snapshot["tables"].items() if name != "identity_users"} == {
            name: value for name, value in checkpoint["tables"].items() if name != "identity_users"}
        for table in snapshot["tables"].values():
            assert table["rows"] >= 0
            _wave3_sha256(table["sha256"])
        assert checkpoint["tables"]["identity_users"]["rows"] == snapshot["tables"]["identity_users"]["rows"]
        _wave3_sha256(checkpoint["tables"]["identity_users"]["sha256"])
    collections = reports["collections"]["persisted_effects"]
    for key, expected in {"lines": 2, "warehouses": 2, "delivery_invoice_collection_tranches": 4, "cancelled_undelivered_tranches": 1,
                          "posting_effects": 22, "invoice_installments": 12, "cancelled_reviewed_installments": 1,
                          "retained_collection_plans": 13, "receipts": 12, "revenue_minor": "69000", "cash_minor": "69000",
                          "cogs_minor": "28000", "fifo_residual_quantity": "0", "fifo_residual_minor": "0", "gl_turnover_minor": "194000"}.items():
        assert collections[key] == expected
    landed = reports["landed-cost"]["persisted_effects"]
    for key, expected in {"line_count": 2, "stock_receipts": 2, "cancelled_bundles": 1, "cancelled_receipt_drafts": 2,
                          "supplier_invoices": 2, "payment_installments": 4, "posting_effects": 9, "expected_turnover_minor": "53002",
                          "capitalized_cost_minor": "18001", "paid_charge_minor": "1001", "paid_minor": "17000", "outstanding_minor": "0"}.items():
        assert landed[key] == expected
    assert landed["warehouses"] == ["MAIN/STOCK", "NORTH/STOCK"] and landed["units"] == ["EA", "KG"]
    assets = reports["fixed-assets"]["persisted_effects"]
    for key, expected in {"asset_status": "Disposed", "source_plans": 4, "native_posting_effects": 4, "cost_minor": "10101",
                          "depreciation_tranches_minor": ["3033", "6067"], "accumulated_minor": "9100", "disposal_carrying_minor": "1001",
                          "proceeds_minor": "1500", "gain_minor": "499", "final_carrying_minor": "0"}.items():
        assert assets[key] == expected
    assert assets["account_balances_minor"] == {"FIXED": "0", "ACCUM": "0", "DEPRECIATION": "9100", "CASH": "-8601", "GAIN": "-499"}
    for scenario, expected_rows in {
        "collections": {"commercial_collection_plans": 13, "commercial_collection_cancellations": 1, "commercial_collection_links": 12},
        "landed-cost": {"landed_cost_plans": 2, "landed_cost_cancellations": 1, "landed_cost_allocations": 4, "landed_cost_links": 1},
        "fixed-assets": {"fixed_assets": 1, "fixed_asset_plans": 4, "fixed_asset_links": 4},
    }.items():
        tables = reports[scenario]["native_restore"]["snapshot"]["tables"]
        assert all(tables[name]["rows"] == count for name, count in expected_rows.items())


def test_wave3_unsuccessful_browser_and_budget_attempts_remain_unaccepted() -> None:
    packet = _wave3_acceptance_packet()
    wrappers = packet["retained_unsuccessful_attempts"]
    assert len(wrappers) == 6
    expected_paths = {
        "output/wave3-browser/collections/report.json", "output/wave3-browser/landed-cost/report.json",
        "output/wave3-browser/fixed-assets/report.json", "output/wave3-browser-final/fixed-assets/report.json",
        "output/global-operating-platform-20261009/commercial/native-1791601404528029400/native-gate.json",
        "output/wave3-python-regression/timeout-result.json",
    }
    assert {wrapper["local_report"] for wrapper in wrappers} == expected_paths
    for wrapper in wrappers:
        report = _retained_report(wrapper)
        if "accepted" in wrapper:
            assert wrapper["accepted"] is False
        if wrapper["local_report"].endswith("native-gate.json"):
            assert report["accepted"] is False and report["native_cases_passed"] is False
            assert report["timed_out"] is True and report["pytest_timeout_seconds"] == 1800
            assert report["pytest_exit_code"] == 124 and report["counts"] is None
        elif wrapper["local_report"].endswith("timeout-result.json"):
            assert report["accepted"] is False and report["outcome"] == "local_budget_exhausted"
            assert report["timeout_seconds"] == 900 and report["counts"] is None
        else:
            assert report["status"] == "failed"
            assert report.get("native_restore") is None
            if wrapper["local_report"] == "output/wave3-browser/collections/report.json":
                # This browser case passed; its stale migration diagnostics
                # refused populated restore. Preserve the aggregate refusal.
                assert report["browser_exit_code"] == 0 and report["browser_counts"]["expected"] == 1
                assert all(report["browser_counts"][key] == 0 for key in ("skipped", "unexpected", "flaky"))
            else:
                assert report["browser_counts"]["unexpected"] > 0 and report["browser_exit_code"] != 0
