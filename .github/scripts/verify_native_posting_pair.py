#!/usr/bin/env python3
"""Verify the indexed wave3 posting pair offline, using only Python's stdlib.

python .github/scripts/verify_native_posting_pair.py --root . --report output/pair-proof.json
Original reports are reconstructed from the published wrappers, including CRLF.
No application imports, original local paths, database, Docker or network needed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any

PAIR = (
    ("enterprise-native-finance-wave3-baseline-806a05db-2026-10-10.json", "806a05db8a6ad442f0c79170277ab209a0fe9049"),
    ("enterprise-native-finance-wave3-candidate-70dffef7-2026-10-10.json", "70dffef7b04446d59de2ff35b39fce1933974aad"),
)
CONFIG_FIELDS = (
    "profile", "seed", "counts", "workers", "repetitions", "max_seconds", "image", "python", "platform",
    "logical_cpus", "processor", "architecture", "docker_version", "docker_engine_resources",
    "postgres_version", "postgres_configuration", "runtime_role_flags",
)
TOTAL_FIELDS = ("debit_minor", "credit_minor", "cash_minor", "equity_minor")


class VerificationError(ValueError):
    """An indexed evidence invariant failed; also enforced under python -O."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in result, f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def read_json(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    value = json.loads(raw, object_pairs_hook=unique_object)
    require(isinstance(value, dict), f"Expected JSON object: {path.name}")
    return value, hashlib.sha256(raw).hexdigest()


def minor_oracle(count: int) -> str:
    """Independent SHA256/integer computation; no posting or pricing imports."""
    require(type(count) is int and count in (100, 1000), "Unsupported oracle prefix")
    total = 0
    for index in range(count):
        prefix = hashlib.sha256(f"enterprise-native-v1:{index}".encode()).hexdigest()[:16]
        total += 1 + int(prefix, 16) % 1_000_000
    return str(total)


def percentile(raw: list[Any], fraction: float) -> float:
    require(bool(raw) and all(type(v) in (int, float) and math.isfinite(v) and v >= 0 for v in raw), "Invalid latency vector")
    return sorted(raw)[math.ceil(len(raw) * fraction) - 1]


def validate_percentiles(raw: list[Any], retained: dict[str, Any]) -> None:
    for name, fraction in (("p50", .5), ("p95", .95), ("p99", .99)):
        require(retained[name] == percentile(raw, fraction), f"Raw percentile mismatch: {name}")


def retained_measurement(packet: dict[str, Any]) -> dict[str, Any]:
    serialization = packet["original_report_serialization"]
    require(serialization == {"encoding": "utf-8", "indent": 2, "ensure_ascii": True,
                              "final_newline": True, "line_endings": "CRLF"}, "Unexpected original serialization")
    measurement = packet["measurement"]
    raw = (json.dumps(measurement, indent=2, ensure_ascii=True) + "\n").replace("\n", "\r\n").encode("utf-8")
    require(hashlib.sha256(raw).hexdigest() == packet["original_report_sha256"], "Original report SHA reconstruction failed")
    require(packet["source_sha256"] == measurement["source_sha256"], "Wrapper/source digest mismatch")
    require(packet["financial_effects_digest"] == measurement["verified_reads"][-1]["financial_effects_digest"], "Wrapper/effect digest mismatch")
    return measurement


def memory_bytes(raw: str) -> int:
    match = re.fullmatch(r"([0-9.]+)([A-Za-z]+)", raw.strip())
    require(match is not None, "Invalid Docker memory measurement")
    value, unit = match.groups()  # type: ignore[union-attr]
    multiplier = {"B": 1, "kB": 1000, "MB": 1000**2, "GB": 1000**3,
                  "KiB": 1024, "MiB": 1024**2, "GiB": 1024**3}[unit]
    return round(float(value) * multiplier)


def resources(report: dict[str, Any]) -> dict[str, Any]:
    sampling = report["resource_sampling"]
    require(sampling["status"] == "complete" and sampling["thread_still_running"] is False and sampling["errors"] == [], "Incomplete resource sampling")
    require(sampling["interval_seconds"] == 10, "Different sampling interval")
    rows = sampling["raw_samples"]
    require(len(rows) >= 2, "Insufficient resource samples")
    require(all(a["elapsed_seconds"] < b["elapsed_seconds"] for a, b in zip(rows, rows[1:], strict=False)), "Unordered resource samples")
    first, last = rows[0], rows[-1]
    require(last["client_cpu_seconds"] >= first["client_cpu_seconds"], "CPU counter decreased")
    return {
        "sample_count": len(rows), "interval_seconds": sampling["interval_seconds"],
        "first_elapsed_seconds": first["elapsed_seconds"], "last_elapsed_seconds": last["elapsed_seconds"],
        "client_cpu_seconds_sample_window_delta": last["client_cpu_seconds"] - first["client_cpu_seconds"],
        "sampled_client_rss_peak_bytes": max(row["client_memory"]["rss_bytes"] for row in rows),
        "client_lifetime_peak_rss_bytes_at_last_sample": last["client_memory"]["process_lifetime_peak_rss_bytes"],
        "sampled_docker_cpu_peak_percent": max(float(row["docker_raw_counters"]["CPUPerc"].rstrip("%")) for row in rows),
        "sampled_docker_ram_peak_bytes": max(memory_bytes(row["docker_raw_counters"]["MemUsage"].split("/")[0]) for row in rows),
        "sampled_lock_waiting_sessions_peak": max(row["postgres_wait_event_type_sessions"].get("Lock", 0) for row in rows),
        "deadlock_counter_first": first["postgres_database_counters"]["deadlocks"],
        "deadlock_counter_last": last["postgres_database_counters"]["deadlocks"],
        "database_counter_sample_window_deltas": {
            key: last["postgres_database_counters"][key] - value
            for key, value in first["postgres_database_counters"].items()},
        "wal_bytes_sample_window_delta": int(last["postgres_wal_counters"]["wal_bytes"]) - int(first["postgres_wal_counters"]["wal_bytes"]),
        "docker_raw_counters_first": first["docker_raw_counters"], "docker_raw_counters_last": last["docker_raw_counters"],
    }


def validate_measurement(report: dict[str, Any], commit: str) -> dict[str, Any]:
    require(report["status"] == "passed" and report["source_unchanged"] is True and report["owned_container_removed"] is True, "Incomplete run/source/cleanup")
    require(report["source_commit"] == report["source_commit_after"] == commit, "Different measured source")
    require(report["source_sha256"] == report["source_sha256_after"] and bool(re.fullmatch(r"[0-9a-f]{64}", report["source_sha256"])), "Changed/invalid source fingerprint")
    require(report["profile"] == "native-three-human-cash-equity-v1" and report["seed"] == "enterprise-native-v1", "Different workload/seed")
    require(report["counts"] == [100, 1000] and report["workers"] == 4 and report["repetitions"] == 3 and report["max_seconds"] == 1800, "Different workload configuration")
    require(report["runtime_role_flags"] == [False, False] and report["cost_per_transaction"] is None, "Privileged role or invented cost")
    require(report["posting_profile"]["enabled"] is False and report.get("snapshot_lines", 0) == 0, "Instrumented/different posting workload")
    configuration = report["postgres_configuration"]
    require(all(configuration[name] == "on" for name in ("fsync", "full_page_writes", "synchronous_commit")), "Durability disabled")
    posting = report["posting"]
    require(posting["requested_cycles"] == posting["admitted_cycles"] == posting["completed_cycles"] == 1000, "Incomplete posting population")
    require(posting["error_count"] == posting["not_admitted_cycles"] == 0 and posting["failed_cycles"] == [], "Failed/nonadmitted postings")
    indices = posting["completed_indices"]
    require(all(type(index) is int for index in indices) and indices == list(range(1000)), "Missing/duplicate/noninteger posting index")
    effects = posting["ordered_effect_ids"]
    require(len(effects) == len(set(effects)) == 1000 and all(isinstance(effect, str) and effect for effect in effects), "Missing/duplicate effect")
    require(posting["expected"] == dict.fromkeys(TOTAL_FIELDS, minor_oracle(1000)), "Posting oracle mismatch")
    require(posting["seconds"] > 0 and math.isfinite(posting["seconds"]) and posting["native_postings_per_second"] == 1000 / posting["seconds"], "Invalid posting duration/throughput")
    raw = posting["raw_cycle_latency_seconds"]
    require(len(raw) == 1000, "Incomplete raw posting vector")
    validate_percentiles(raw, posting["cycle_latency_seconds"])
    profiles = report["verified_reads"]
    require([profile["count"] for profile in profiles] == [100, 1000], "Missing read prefix")
    requests = executes = visits = 0
    summaries = []
    for profile in profiles:
        count = profile["count"]
        oracle = minor_oracle(count)
        population = json.dumps(effects[:count], sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        require(hashlib.sha256(population).hexdigest() == profile["dataset_effect_ids_sha256"], "Read dataset/posting population mismatch")
        require(profile["status"] == "passed" and profile["expected"] == dict.fromkeys(TOTAL_FIELDS, oracle), "Read-prefix oracle/status mismatch")
        require(profile["cache_policy"] == "both warmed; alternating modes", "Different cache policy")
        require(set(profile["samples"]) == {"per_effect_baseline", "bounded_batch"}, "Different read modes")
        medians: dict[str, float] = {}
        for mode, samples in profile["samples"].items():
            require([sample["repetition"] for sample in samples] == [0, 1, 2], "Incomplete read repetitions")
            for sample in samples:
                require(sample["status"] == "complete" and sample["error_count"] == 0 and sample["requested_effects"] == sample["effects"] == count, "Incomplete read sample")
                require(sample["debit_minor"] == sample["credit_minor"] == oracle, "Retained read financial oracle mismatch")
                require(sample["effects_digest"] == profile["financial_effects_digest"], "Within-database read digest mismatch")
                latencies = sample["raw_request_latency_seconds"]
                expected_requests = count if mode == "per_effect_baseline" else count // 100
                require(len(latencies) == expected_requests, "Incomplete read latency vector")
                require(sample["request_unit"] == ("one_effect" if mode == "per_effect_baseline" else "up_to_100_effects"), "Different read request unit")
                validate_percentiles(latencies, sample["request_latency_seconds"])
                require(sample["seconds"] > 0 and math.isfinite(sample["seconds"]) and sample["verified_effects_per_second"] == count / sample["seconds"], "Invalid read throughput")
                requests += len(latencies)
                executes += sample["client_execute_calls"]
                visits += count
            medians[mode] = sorted(sample["seconds"] for sample in samples)[1]
        require(profile["median_seconds_baseline"] == medians["per_effect_baseline"] and profile["median_seconds_optimized"] == medians["bounded_batch"], "Read median mismatch")
        require(profile["measured_speedup"] == medians["per_effect_baseline"] / medians["bounded_batch"], "Read speedup mismatch")
        summaries.append({"count": count, "expected_minor": oracle, "financial_effects_digest": profile["financial_effects_digest"],
                          "median_seconds_per_effect": medians["per_effect_baseline"], "median_seconds_bounded_batch": medians["bounded_batch"],
                          "within_source_read_speedup": profile["measured_speedup"]})
    require(requests == 3333 and visits == 6600, "Incomplete verified read population")
    return {"source_commit": commit, "source_sha256": report["source_sha256"], "schema_revision": report["revision"],
            "wall_seconds": report["wall_seconds"], "posting_seconds": posting["seconds"], "native_cycles_per_second": posting["native_postings_per_second"],
            "cycle_latency_seconds": posting["cycle_latency_seconds"], "posting_cycles": 1000, "raw_cycle_samples": len(raw),
            "measured_read_requests": requests, "warmup_read_requests": 4, "measured_client_execute_calls": executes,
            "verified_effect_visits": visits, "reads": summaries, "resources": resources(report), "cost_per_transaction": None}


def compare_configuration(baseline: dict[str, Any], candidate: dict[str, Any]) -> None:
    for field in CONFIG_FIELDS:
        require(baseline[field] == candidate[field], f"Matched configuration differs: {field}")


def verify_pair(root: Path) -> dict[str, Any]:
    root = root.resolve()
    index, index_sha = read_json(root / "docs/execution/benchmarks/INDEX.v1.json")
    metadata, metadata_sha = read_json(root / "docs/execution/GLOBAL_INTEGRITY_ACCEPTANCE_2026-10-10.json")
    measurements = []
    summaries = []
    paths = []
    for filename, commit in PAIR:
        relative = "docs/execution/benchmarks/" + filename
        paths.append(relative)
        matching = [entry for entry in index["entries"] if entry["artifact"] == relative]
        require(len(matching) == 1 and matching[0]["status"] == "verified", "Missing/duplicate/unverified index entry")
        packet, sha = read_json(root / relative)
        entry = matching[0]
        require(sha == entry["artifact_sha256"], "Indexed artifact SHA mismatch")
        require(entry["profile_id"] == packet["profile_id"], "Indexed profile mismatch")
        require(set(entry["digest_fields"]) == {"source_sha256", "financial_effects_digest", "original_report_sha256"}, "Different indexed digest contract")
        measurement = retained_measurement(packet)
        summary = validate_measurement(measurement, commit)
        summary.update(artifact=relative, artifact_sha256=sha, original_report_sha256=packet["original_report_sha256"])
        measurements.append(measurement)
        summaries.append(summary)
    require(metadata["matched_pair_artifacts"] == paths, "Acceptance metadata/pair mismatch")
    require(metadata["asset_lock_fix_source"] == PAIR[1][1], "Acceptance metadata candidate mismatch")
    compare_configuration(*measurements)
    require(datetime.fromisoformat(measurements[0]["finished_at"]) <= datetime.fromisoformat(measurements[1]["started_at"]), "Posting runs overlapped")
    baseline, candidate = summaries
    def change(before: float, after: float) -> float:
        return (after / before - 1) * 100

    return {"schema_version": "standalone-native-posting-pair-verification-v1", "status": "passed",
            "index_sha256": index_sha, "acceptance_metadata_sha256": metadata_sha,
            "independent_oracle_minor": {str(count): minor_oracle(count) for count in (100, 1000)},
            "common_configuration": {field: measurements[0][field] for field in CONFIG_FIELDS},
            "baseline": baseline, "candidate": candidate,
            "candidate_change_percent": {
                "native_cycles_per_second": change(baseline["native_cycles_per_second"], candidate["native_cycles_per_second"]),
                "posting_seconds": change(baseline["posting_seconds"], candidate["posting_seconds"]),
                "p50": change(baseline["cycle_latency_seconds"]["p50"], candidate["cycle_latency_seconds"]["p50"]),
                "p95": change(baseline["cycle_latency_seconds"]["p95"], candidate["cycle_latency_seconds"]["p95"]),
                "p99": change(baseline["cycle_latency_seconds"]["p99"], candidate["cycle_latency_seconds"]["p99"]),
                "client_cpu_sample_window_delta": change(baseline["resources"]["client_cpu_seconds_sample_window_delta"], candidate["resources"]["client_cpu_seconds_sample_window_delta"]),
                "sampled_client_rss_peak": change(baseline["resources"]["sampled_client_rss_peak_bytes"], candidate["resources"]["sampled_client_rss_peak_bytes"]),
                "sampled_docker_ram_peak": change(baseline["resources"]["sampled_docker_ram_peak_bytes"], candidate["resources"]["sampled_docker_ram_peak_bytes"]),
                "bounded_batch_1000_seconds": change(baseline["reads"][-1]["median_seconds_bounded_batch"], candidate["reads"][-1]["median_seconds_bounded_batch"])},
            "cross_database_digest_equality_tested": False,
            "limits": ["Offline reconstruction and arithmetic verification does not rerun posting or independently audit the original database.",
                       "One posting population per source; no causal/statistical or competitor superiority claim.",
                       "Three-human native two-line cash/equity cycles include authentication; not HTTP or mixed ERP TPS.",
                       "Read request/client execute counts are not server-side statement counts.",
                       "10-second resource windows include reads/observer and may miss transient spikes or locks.",
                       "Client lifetime RSS begins before admission; track_io_timing=off does not imply no I/O.",
                       "Adverse client CPU/RSS and bounded-batch read observations are retained.",
                       "Cost is null; failover/RPO/RTO are unmeasured."]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="Repository or extracted source archive root")
    parser.add_argument("--report", type=Path, required=True, help="Fresh JSON output; existing files are never overwritten")
    args = parser.parse_args()
    try:
        require(not args.report.exists(), "Report already exists; choose fresh output")
        report = verify_pair(args.root)
    except (VerificationError, KeyError, TypeError, ValueError, OSError) as exc:
        report = {"schema_version": "standalone-native-posting-pair-verification-v1", "status": "failed",
                  "failure_type": type(exc).__name__, "failure": str(exc)}
    try:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        with args.report.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(report, stream, indent=2, ensure_ascii=True, allow_nan=False)
            stream.write("\n")
    except OSError as exc:
        print(json.dumps({"status": "failed", "failure": str(exc)}))
        return 1
    print(json.dumps({"status": report["status"], "report": str(args.report),
                      "report_sha256": hashlib.sha256(args.report.read_bytes()).hexdigest()}))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
