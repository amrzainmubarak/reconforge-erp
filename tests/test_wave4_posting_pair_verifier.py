"""Portable offline pair verification; independently generated 1000-cycle mocks."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import shutil
import subprocess
import sys
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location("wave4_pair_offline", ROOT / ".github/scripts/verify_wave4_posting_pair.py")
assert SPEC is not None and SPEC.loader is not None
VERIFIER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFIER)
# Only nonfinancial environment/resource metadata is borrowed. Financial effect
# populations, oracle totals, latency vectors and repeated reads are built below.
ENVIRONMENT = json.loads((ROOT / "tests/fixtures/enterprise-warmup-20-ea83335c.json").read_text())


def oracle(count: int) -> str:
    return str(sum(1 + int.from_bytes(hashlib.sha256(f"enterprise-native-v1:{index}".encode()).digest()[:8], "big") % 1_000_000
                   for index in range(count)))


def percentiles(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    return {name: ordered[math.ceil(len(values) * fraction) - 1] for name, fraction in (("p50", .5), ("p95", .95), ("p99", .99))}


def mock_packet(repetition: int, variant: str, position: int) -> dict[str, Any]:
    packet = deepcopy(ENVIRONMENT)
    label = f"{repetition}-{variant}"
    commit = VERIFIER.COMMITS[variant]
    packet.update(source_commit=commit, source_commit_after=commit,
                  source_sha256=hashlib.sha256(variant.encode()).hexdigest(),
                  source_sha256_after=hashlib.sha256(variant.encode()).hexdigest(),
                  counts=[100, 1000], max_seconds=1800)
    start = datetime(2026, 10, 10, tzinfo=UTC) + timedelta(hours=position)
    packet.update(started_at=start.isoformat(), finished_at=(start + timedelta(minutes=30)).isoformat())
    packet["runtime_root"] = f"/absent-original-host/{variant}"
    packet["command"] = ["original-python.exe", "benchmark_enterprise_finance.py", "--counts", "100", "1000",
                         "--workers", "4", "--repetitions", "3", "--posting-warmup", "20", "--max-seconds", "1800", "--output", "original-output"]
    packet["posting_profile"] = {"enabled": False, "raw_phase_observations": [], "phase_totals": {}, "statement_templates": [],
                                 "function_profile": {"enabled": False, "functions": []}}
    effects = [f"PST-{label}-{index:04d}" for index in range(1000)]
    durations = [.4 + (index % 10) / 100 for index in range(1000)]
    seconds = 90.0 + repetition * 10 + (20 if variant == "candidate" else 0)
    packet["posting"] = {"completed_cycles": 1000, "requested_cycles": 1000, "admitted_cycles": 1000,
        "failed_cycles": [], "error_count": 0, "not_admitted_cycles": 0, "completed_indices": list(range(1000)),
        "ordered_effect_ids": effects, "seconds": seconds, "native_postings_per_second": 1000 / seconds,
        "client_process_cpu_seconds": 10.0 + repetition * 2 + (5 if variant == "candidate" else 0),
        "raw_cycle_latency_seconds": durations, "cycle_latency_seconds": percentiles(durations),
        "expected": dict.fromkeys(("debit_minor", "credit_minor", "cash_minor", "equity_minor"), oracle(1000))}
    packet["posting_warmup"].update(indices=list(range(1000, 1020)), effect_ids=[f"PST-{label}-warm-{index}" for index in range(20)])
    reads = []
    for count in (100, 1000):
        total = oracle(count)
        digest = hashlib.sha256(f"retained-{label}-{count}".encode()).hexdigest()
        profile: dict[str, Any] = {"count": count, "status": "passed", "expected": dict.fromkeys(packet["posting"]["expected"], total),
            "dataset_effect_ids_sha256": hashlib.sha256(json.dumps(effects[:count], sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest(),
            "cache_policy": "both warmed; alternating modes", "samples": {}, "financial_effects_digest": digest}
        for mode in ("per_effect_baseline", "bounded_batch"):
            samples = []
            for index in range(3):
                latency = [.001 + index / 10000] * (count if mode == "per_effect_baseline" else count // 100)
                elapsed = (1.0 if mode == "per_effect_baseline" else .5) + index / 100 + (.2 if variant == "candidate" else 0)
                samples.append({"repetition": index, "status": "complete", "debit_minor": total, "credit_minor": total,
                    "requested_effects": count, "effects": count, "error_count": 0, "effects_digest": digest,
                    "raw_request_latency_seconds": latency, "request_latency_seconds": percentiles(latency),
                    "request_unit": "one_effect" if mode == "per_effect_baseline" else "up_to_100_effects",
                    "seconds": elapsed, "verified_effects_per_second": count / elapsed})
            profile["samples"][mode] = samples
        profile.update(median_seconds_baseline=profile["samples"]["per_effect_baseline"][1]["seconds"],
                       median_seconds_optimized=profile["samples"]["bounded_batch"][1]["seconds"])
        profile["measured_speedup"] = profile["median_seconds_baseline"] / profile["median_seconds_optimized"]
        reads.append(profile)
    packet["verified_reads"] = reads
    container = hashlib.sha256(f"container-{label}".encode()).hexdigest()
    final = json.loads(packet["container_resources_final_sample"])
    final["Container"] = container
    packet["container_resources_final_sample"] = json.dumps(final)
    packet["resource_sampling"]["host_processor_observation"] = {
        "requested": True, "platform": "win32", "status": "enabled", "cleanup": {"status": "closed", "api_status": 0}}
    for index, row in enumerate(packet["resource_sampling"]["raw_samples"]):
        row["host_processor"] = {"status": "priming" if index == 0 else "available",
            "processor_performance_percent": None if index == 0 else 123.5,
            "processor_frequency_mhz": None if index == 0 else 3100.0,
            "power": {"status": "available", "ac_online": True, "battery_saver_on": False}}
    return packet


def write_json(path: Path, value: dict[str, Any]) -> str:
    raw = (json.dumps(value, indent=2, allow_nan=False) + "\n").encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def fixture(directory: Path) -> tuple[Path, str]:
    manifest: dict[str, Any] = {"schema_version": "wave4-native-posting-pair-manifest-v1", "status": "passed",
                             "pairs": 3, "count": 1000, "commits": dict(VERIFIER.COMMITS), "runs": []}
    for position, (repetition, variant) in enumerate(VERIFIER.ORDER):
        relative = f"{repetition}-{variant}/result.json"
        digest = write_json(directory / relative, mock_packet(repetition, variant, position))
        manifest["runs"].append({"repetition": repetition, "variant": variant, "report": relative,
                                 "report_sha256": digest, "child_exit_code": 0})
    path = directory / "manifest.json"
    return path, write_json(path, manifest)


def rewrite_packet(path: Path, record_index: int, mutate: Any) -> str:
    manifest = json.loads(path.read_bytes())
    record = manifest["runs"][record_index]
    report = path.parent / record["report"]
    packet = json.loads(report.read_bytes())
    mutate(packet)
    record["report_sha256"] = write_json(report, packet)
    return write_json(path, manifest)


def test_independent_thousand_cycle_populations_and_adverse_changes_are_verified(tmp_path: Path) -> None:
    manifest, digest = fixture(tmp_path)
    report = VERIFIER.verify_manifest(manifest, digest)
    assert report["status"] == "passed"
    assert report["financial_verification"] == "passed"
    assert report["environment_equivalence"]["dynamic_host_power_constant"] is True
    assert report["environment_equivalence"]["dynamic_host_power_classification"] == "constant_observed"
    assert report["performance_comparison_accepted"] is False
    observed = report["runs"][0]["host_observations"]
    assert observed["power_counts"] == {"ac": observed["sample_count"], "battery": 0, "unavailable": 0}
    assert observed["counter_status_counts"]["priming"] == 1
    assert observed["quantiles"]["processor_frequency_mhz"]["median"] == 3100.0
    assert observed["quantiles"]["processor_frequency_mhz"]["unavailable_samples"] == 1
    assert observed["quantiles"]["processor_performance_percent"]["p95"] == 123.5
    assert report["independent_oracle_minor"] == {"100": "46669102", "1000": "493671004"}
    assert report["measured_cycles_per_variant"] == 3000 and report["warmup_cycles_per_variant"] == 60
    assert report["distinct_native_effects_including_warmup"] == 6120 and report["distinct_container_count"] == 6
    assert report["medians"]["baseline"]["posting_seconds"] == 110.0
    assert report["medians"]["candidate"]["posting_seconds"] == 130.0
    assert report["candidate_change_percent"]["posting_seconds"] == pytest.approx((130 / 110 - 1) * 100)
    assert report["candidate_change_percent"]["client_cpu_seconds"] > 0
    assert report["candidate_change_percent"]["bounded_batch_read_seconds"] > 0
    assert report["cost_per_success_currency"] is None and report["cross_database_digest_equality_tested"] is False


def test_changed_host_power_keeps_financial_proof_and_refuses_performance_acceptance(tmp_path: Path) -> None:
    manifest, _ = fixture(tmp_path)

    def mutate(packet: dict[str, Any]) -> None:
        packet["resource_sampling"]["raw_samples"][-1]["host_processor"]["power"].update(
            ac_online=False, battery_saver_on=True)

    digest = rewrite_packet(manifest, 2, mutate)
    report = VERIFIER.verify_manifest(manifest, digest)
    assert report["status"] == report["financial_verification"] == "passed"
    assert report["performance_comparison_accepted"] is False
    environment = report["environment_equivalence"]
    assert environment["static_configuration_equal"] is True
    assert environment["dynamic_host_power_constant"] is False
    assert environment["dynamic_host_power_classification"] == "changed"
    assert environment["power_counts"]["battery"] == 1 and environment["power_counts"]["unavailable"] == 0
    assert environment["observed_power_states"] == ["ac", "battery"]
    assert report["runs"][2]["host_observations"]["battery_saver_counts"]["on"] == 1
    assert "unavailable" in environment["frequency_or_performance_phase_binding"]


@pytest.mark.parametrize("invalid", [None, 0, 1, "false", False])
def test_power_admission_requires_available_status_and_exact_boolean(tmp_path: Path, invalid: Any) -> None:
    manifest, _ = fixture(tmp_path)

    def mutate(packet: dict[str, Any]) -> None:
        power = packet["resource_sampling"]["raw_samples"][-1]["host_processor"]["power"]
        if invalid is False:
            power.update(status="unavailable", ac_online=False, battery_saver_on=False)
        else:
            power.update(ac_online=invalid, battery_saver_on=0)

    report = VERIFIER.verify_manifest(manifest, rewrite_packet(manifest, 1, mutate))
    assert report["financial_verification"] == "passed"
    assert report["environment_equivalence"]["dynamic_host_power_constant"] is False
    assert report["environment_equivalence"]["dynamic_host_power_classification"] == "unverified"
    assert report["performance_comparison_accepted"] is False
    observed = report["runs"][1]["host_observations"]
    assert observed["power_counts"]["unavailable"] == 1
    assert observed["power_counts"]["battery"] == 0
    assert observed["battery_saver_counts"]["unavailable"] == 1


def test_absent_power_and_missing_counter_values_remain_explicitly_unavailable(tmp_path: Path) -> None:
    manifest, _ = fixture(tmp_path)

    def mutate(packet: dict[str, Any]) -> None:
        for sample in packet["resource_sampling"]["raw_samples"]:
            sample["host_processor"] = {"status": "unavailable", "processor_performance_percent": None,
                                        "processor_frequency_mhz": None}

    report = VERIFIER.verify_manifest(manifest, rewrite_packet(manifest, 0, mutate))
    observed = report["runs"][0]["host_observations"]
    assert report["financial_verification"] == "passed"
    assert report["environment_equivalence"]["dynamic_host_power_constant"] is False
    assert observed["power_counts"] == {"ac": 0, "battery": 0, "unavailable": observed["sample_count"]}
    assert observed["counter_status_counts"] == {"unavailable": observed["sample_count"]}
    for quantile in observed["quantiles"].values():
        assert quantile["available_samples"] == 0
        assert quantile["unavailable_samples"] == observed["sample_count"]
        assert all(quantile[name] is None for name in ("min", "median", "p50", "p95", "p99", "max"))


def test_boolean_counter_values_are_refused_instead_of_becoming_zero(tmp_path: Path) -> None:
    manifest, _ = fixture(tmp_path)

    def mutate(packet: dict[str, Any]) -> None:
        packet["resource_sampling"]["raw_samples"][-1]["host_processor"]["processor_frequency_mhz"] = False

    with pytest.raises(ValueError, match="numeric value invalid"):
        VERIFIER.verify_manifest(manifest, rewrite_packet(manifest, 1, mutate))


def test_explicit_trusted_anchor_cannot_be_replaced_by_self_checksum(tmp_path: Path) -> None:
    manifest, digest = fixture(tmp_path)
    with pytest.raises(ValueError, match="trusted manifest"):
        VERIFIER.verify_manifest(manifest, "")
    with pytest.raises(ValueError, match="Trusted manifest"):
        VERIFIER.verify_manifest(manifest, "0" * 64)
    manifest.write_bytes(manifest.read_bytes() + b" ")
    with pytest.raises(ValueError, match="Trusted manifest"):
        VERIFIER.verify_manifest(manifest, digest)


def test_original_raw_report_bytes_are_bound_even_if_json_content_is_unchanged(tmp_path: Path) -> None:
    manifest, digest = fixture(tmp_path)
    target = tmp_path / "1-baseline/result.json"
    target.write_bytes(target.read_bytes().replace(b"\n", b"\r\n"))
    with pytest.raises(ValueError, match="Raw report SHA"):
        VERIFIER.verify_manifest(manifest, digest)


@pytest.mark.parametrize("damage", ["missing", "duplicate_path", "wrong_order", "child_failure", "wrong_commit", "unsafe_path"])
def test_bad_manifest_membership_or_order_is_refused(tmp_path: Path, damage: str) -> None:
    path, _ = fixture(tmp_path)
    manifest = json.loads(path.read_bytes())
    if damage == "missing":
        manifest["runs"].pop()
    elif damage == "duplicate_path":
        manifest["runs"][1]["report"] = manifest["runs"][0]["report"]
    elif damage == "wrong_order":
        manifest["runs"][2], manifest["runs"][3] = manifest["runs"][3], manifest["runs"][2]
    elif damage == "child_failure":
        manifest["runs"][3]["child_exit_code"] = 1
    elif damage == "wrong_commit":
        manifest["commits"]["candidate"] = "0" * 40
    elif damage == "unsafe_path":
        manifest["runs"][1]["report"] = "../outside.json"
    with pytest.raises(ValueError):
        VERIFIER.verify_manifest(path, write_json(path, manifest))


@pytest.mark.parametrize("damage", [
    "population_missing", "duplicate_population", "invented_effect", "wrong_oracle", "wrong_percentile", "wrong_median",
    "cross_config", "source_changed", "resource_error", "counter_reset", "duplicate_container", "overlap", "warm_overlap",
    "current_role_boolean", "function_profile", "observer_close_failure",
])
def test_resealed_adversarial_reports_cannot_bypass_financial_or_resource_contract(tmp_path: Path, damage: str) -> None:
    path, _ = fixture(tmp_path)
    first = json.loads((tmp_path / "1-baseline/result.json").read_bytes())

    def mutate(packet: dict[str, Any]) -> None:
        if damage == "population_missing":
            packet["posting"]["completed_indices"].pop()
        elif damage == "duplicate_population":
            packet["posting"]["ordered_effect_ids"] = first["posting"]["ordered_effect_ids"]
            packet["verified_reads"] = first["verified_reads"]
        elif damage == "invented_effect":
            packet["posting"]["ordered_effect_ids"][-1] = "PST-unique-invented"
        elif damage == "wrong_oracle":
            packet["posting"]["expected"]["cash_minor"] = "493671005"
        elif damage == "wrong_percentile":
            packet["posting"]["cycle_latency_seconds"]["p99"] = 999.0
        elif damage == "wrong_median":
            packet["verified_reads"][-1]["median_seconds_optimized"] = 9.0
        elif damage == "cross_config":
            packet["postgres_configuration"]["work_mem"] = "different"
        elif damage == "source_changed":
            packet["source_commit_after"] = "0" * 40
        elif damage == "resource_error":
            packet["resource_sampling"]["errors"] = [{"exception_type": "OSError"}]
        elif damage == "counter_reset":
            packet["resource_sampling"]["raw_samples"][2]["postgres_database_counters"]["xact_commit"] = 0
        elif damage == "duplicate_container":
            packet["container_resources_final_sample"] = first["container_resources_final_sample"]
        elif damage == "overlap":
            packet["started_at"] = first["started_at"]
        elif damage == "warm_overlap":
            packet["posting_warmup"]["effect_ids"][0] = packet["posting"]["ordered_effect_ids"][0]
        elif damage == "current_role_boolean":
            packet["runtime_role_flags"] = [0, 0]
        elif damage == "function_profile":
            packet["posting_profile"]["function_profile"]["enabled"] = True
        elif damage == "observer_close_failure":
            packet["resource_sampling"]["host_processor_observation"]["cleanup"]["status"] = "close_failed"

    digest = rewrite_packet(path, 1, mutate)
    with pytest.raises(ValueError):
        VERIFIER.verify_manifest(path, digest)


@pytest.mark.parametrize("document", ["manifest", "report"])
def test_duplicate_json_keys_are_rejected_after_raw_resealing(tmp_path: Path, document: str) -> None:
    path, digest = fixture(tmp_path)
    target = path if document == "manifest" else tmp_path / "1-baseline/result.json"
    target.write_bytes(target.read_bytes().replace(b'"status": "passed"', b'"status": "passed", "status": "passed"', 1))
    if document == "report":
        manifest = json.loads(path.read_bytes())
        manifest["runs"][0]["report_sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
        digest = write_json(path, manifest)
    else:
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="Duplicate JSON key"):
        VERIFIER.verify_manifest(path, digest)


@pytest.mark.parametrize("flags", [[], ["-I"], ["-I", "-O"]])
def test_cli_is_portable_outside_checkout_and_optimization_keeps_checks(tmp_path: Path, flags: list[str]) -> None:
    tools = tmp_path / "tools"
    tools.mkdir()
    for name in ("verify_wave4_posting_pair.py", "benchmark_global_engineering_pair.py", "verify_native_posting_pair.py"):
        shutil.copyfile(ROOT / ".github/scripts" / name, tools / name)
    path, digest = fixture(tmp_path / "packet")
    output = tmp_path / "proof.json"
    command = [sys.executable, *flags, str(tools / "verify_wave4_posting_pair.py"), "--manifest", str(path),
               "--manifest-sha256", digest, "--report", str(output)]
    result = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, timeout=15, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(output.read_bytes())["status"] == "passed"
    before = output.read_bytes()
    repeated = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, timeout=15, check=False)
    assert repeated.returncode == 1 and output.read_bytes() == before
    command[-1] = str(tmp_path / "wrong-anchor-proof.json")
    command[command.index("--manifest-sha256") + 1] = "0" * 64
    refused = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, timeout=15, check=False)
    assert refused.returncode == 1
    assert json.loads(Path(command[-1]).read_bytes())["status"] == "failed"
