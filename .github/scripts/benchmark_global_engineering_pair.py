"""Alternate fresh genuine posting populations and verify their raw evidence.

Stdlib verifier: no ReconForge posting, pricing or accounting imports. This
creates owned synthetic databases through the existing bounded benchmark. Each
pair is a fresh server/population, not a repeated read of one posting sample.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import statistics
import subprocess  # nosec B404
import sys
from pathlib import Path
from typing import Any

CONFIG = ("profile", "seed", "counts", "workers", "repetitions", "posting_warmup_cycles", "max_seconds", "image",
          "python", "platform", "logical_cpus", "processor", "architecture", "docker_version", "docker_engine_resources",
          "postgres_version", "postgres_configuration", "runtime_role_flags")

_spec = importlib.util.spec_from_file_location("retained_pair_verifier", Path(__file__).with_name("verify_native_posting_pair.py"))
if _spec is None or _spec.loader is None:
    raise RuntimeError("Independent retained verifier is absent")
_retained = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_retained)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def verify(packet: dict[str, Any], root: Path, commit: str, count: int) -> dict[str, Any]:
    require(packet["status"] == "passed" and packet["source_unchanged"] and packet["owned_container_removed"], "Run/source/cleanup failed")
    require(packet["source_commit"] == packet["source_commit_after"] == commit, "Source changed")
    require(packet["source_sha256"] == packet["source_sha256_after"], "Source fingerprint changed")
    require(Path(packet["runtime_root"]).resolve() == root, "Runtime root differs")
    require(packet["runtime_role_flags"] == [False, False] and not packet["posting_profile"]["enabled"], "Privileged/instrumented run")
    require(all(packet["postgres_configuration"][name] == "on" for name in ("fsync", "synchronous_commit", "full_page_writes")), "Durability differs")
    posting = packet["posting"]
    require(posting["completed_indices"] == list(range(count)), "Missing posting population")
    require(posting["requested_cycles"] == posting["admitted_cycles"] == posting["completed_cycles"] == count, "Incomplete financial workload")
    require(not posting["failed_cycles"] and posting["error_count"] == posting["not_admitted_cycles"] == 0, "Financial failure")
    effects = posting["ordered_effect_ids"]
    require(len(effects) == len(set(effects)) == count and all(isinstance(value, str) and value for value in effects), "Missing/duplicate effect")
    require(all(type(value) is int for value in posting["completed_indices"]), "Noninteger posting index")
    require(packet["profile"] == "native-three-human-cash-equity-v1" and packet["seed"] == "enterprise-native-v1", "Different financial workload")
    require(packet["counts"] == ([100, count] if count > 100 else [count]), "Different read populations")
    require(packet["workers"] == 4 and packet["repetitions"] == 3 and packet.get("snapshot_lines", 0) == 0, "Different work shape")
    require(type(posting["seconds"]) in (int, float) and math.isfinite(posting["seconds"]) and posting["seconds"] > 0
            and posting["native_postings_per_second"] == count / posting["seconds"], "Invalid posting throughput")
    require(type(posting["client_process_cpu_seconds"]) in (int, float) and math.isfinite(posting["client_process_cpu_seconds"])
            and posting["client_process_cpu_seconds"] > 0, "Invalid client CPU")
    total = sum(1 + int(hashlib.sha256(f"{packet['seed']}:{index}".encode()).hexdigest()[:16], 16) % 1_000_000 for index in range(count))
    expected = dict.fromkeys(("debit_minor", "credit_minor", "cash_minor", "equity_minor"), str(total))
    require(posting["expected"] == expected, "Independent integer posting oracle differs")
    require([profile["count"] for profile in packet["verified_reads"]] == packet["counts"], "Missing read prefix")
    for profile in packet["verified_reads"]:
        prefix = sum(1 + int(hashlib.sha256(f"{packet['seed']}:{index}".encode()).hexdigest()[:16], 16) % 1_000_000 for index in range(profile["count"]))
        population = json.dumps(effects[:profile["count"]], sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        require(hashlib.sha256(population).hexdigest() == profile["dataset_effect_ids_sha256"], "Read population differs from posted effects")
        require(profile["status"] == "passed" and profile["expected"] == dict.fromkeys(expected, str(prefix)), "Financial read failed")
        require(profile["cache_policy"] == "both warmed; alternating modes" and set(profile["samples"]) == {"per_effect_baseline", "bounded_batch"}, "Different read modes")
        medians = {}
        for mode, samples in profile["samples"].items():
            require([sample["repetition"] for sample in samples] == [0, 1, 2], "Missing repeated read samples")
            for sample in samples:
                require(sample["status"] == "complete" and sample["debit_minor"] == sample["credit_minor"] == str(prefix), "Independent retained-effect oracle differs")
                require(sample["requested_effects"] == sample["effects"] == profile["count"] and sample["error_count"] == 0, "Incomplete read")
                require(sample["effects_digest"] == profile["financial_effects_digest"], "Within-source effect digest differs")
                require(len(sample["raw_request_latency_seconds"]) == (profile["count"] if mode == "per_effect_baseline" else math.ceil(profile["count"] / 100)), "Missing read latency")
                _retained.validate_percentiles(sample["raw_request_latency_seconds"], sample["request_latency_seconds"])
                require(sample["request_unit"] == ("one_effect" if mode == "per_effect_baseline" else "up_to_100_effects"), "Different read request")
                require(type(sample["seconds"]) in (int, float) and math.isfinite(sample["seconds"]) and sample["seconds"] > 0
                        and sample["verified_effects_per_second"] == profile["count"] / sample["seconds"], "Invalid read throughput")
            medians[mode] = statistics.median(sample["seconds"] for sample in samples)
        require(profile["median_seconds_baseline"] == medians["per_effect_baseline"] and profile["median_seconds_optimized"] == medians["bounded_batch"]
                and profile["measured_speedup"] == medians["per_effect_baseline"] / medians["bounded_batch"], "Invalid retained read medians")
    raw = posting["raw_cycle_latency_seconds"]
    require(len(raw) == count and all(type(value) in (float, int) and math.isfinite(value) and value > 0 for value in raw), "Invalid raw latency")
    for label, fraction in (("p50", .5), ("p95", .95), ("p99", .99)):
        require(posting["cycle_latency_seconds"][label] == sorted(raw)[math.ceil(count * fraction) - 1], "Percentile differs from raw observations")
    warm = packet["posting_warmup"]
    size = packet["posting_warmup_cycles"]
    require(type(size) is int and 10 <= size <= 100 and warm["status"] == "passed" and warm["completed_cycles"] == size
            and warm["outside_measured_population"] is True and warm["indices"] == list(range(count, count + size))
            and all(type(value) is int for value in warm["indices"]), "Missing genuine warmup")
    require(len(warm["effect_ids"]) == len(set(warm["effect_ids"])) == size and all(isinstance(value, str) and value for value in warm["effect_ids"])
            and not set(warm["effect_ids"]) & set(effects), "Warmup effects are missing or overlap measured population")
    require(len(warm["raw_cycle_latency_seconds"]) == size and all(type(value) in (int, float) and math.isfinite(value) and value > 0
            for value in warm["raw_cycle_latency_seconds"]), "Missing warmup latencies")
    resource_summary = _retained.resources(packet)
    before, after = (packet[name]["parsed"] for name in ("posting_container_counters_before", "posting_container_counters_after"))
    cpu = (after["cpu_microseconds"]["usage_usec"] - before["cpu_microseconds"]["usage_usec"]) / 1_000_000
    require(cpu > 0, "Missing kernel CPU delta")
    return {"count": count, "oracle_total_minor": str(total), "posting_seconds": posting["seconds"],
            "throughput": posting["native_postings_per_second"], **posting["cycle_latency_seconds"],
            "client_cpu_seconds": posting["client_process_cpu_seconds"], "container_cpu_seconds": cpu,
            "total_cpu_seconds_per_success": (cpu + posting["client_process_cpu_seconds"]) / count,
            "container_lifetime_peak_memory_bytes": after["container_lifetime_peak_memory_bytes"],
            "client_lifetime_peak_memory_bytes": max(row["client_memory"]["process_lifetime_peak_rss_bytes"] for row in packet["resource_sampling"]["raw_samples"]),
            "resource_sample_window": resource_summary,
            "bounded_batch_read_seconds": statistics.median(packet["verified_reads"][-1]["samples"]["bounded_batch"][i]["seconds"] for i in range(3)),
            "cost_per_success_currency": None,
            "limits": ["CPU counter boundaries include cgroup exec/observer overhead", "memory peaks include startup and warmup",
                       "single entity USD cash/equity native repositories including current identity checks; no HTTP/mixed ERP equivalence",
                       "no supplied monetary resource cost model; no cross-vendor ranking"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--count", type=int, default=1000, choices=(1000, 10000, 100000, 1000000))
    parser.add_argument("--pairs", type=int, default=3, choices=range(3, 7))
    parser.add_argument("--max-seconds", type=int, default=1800)
    args = parser.parse_args()
    require(30 <= args.max_seconds <= 7200, "Resource budget must be bounded")
    roots = {"baseline": args.baseline.resolve(), "candidate": args.candidate.resolve()}
    output = args.output.resolve()
    require(not (output / "pair.json").exists(), "Prior evidence must be preserved")
    output.mkdir(parents=True, exist_ok=True)
    commits = {label: subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True, timeout=30).strip() for label, root in roots.items()}  # nosec B603 B607
    state: dict[str, Any] = {"schema_version": 1, "status": "running", "pairs": args.pairs, "count": args.count,
                            "commits": commits, "runs": [], "order": "BC,CB,BC alternating; each run fresh server and financial population"}
    reference = None
    try:
        for repetition in range(args.pairs):
            for label in (("baseline", "candidate") if repetition % 2 == 0 else ("candidate", "baseline")):
                destination = output / f"{repetition + 1}-{label}"
                root = roots[label]
                argv = [sys.executable, str(root / ".github/scripts/benchmark_enterprise_finance.py"), "--counts", "100", str(args.count),
                        "--workers", "4", "--repetitions", "3", "--posting-warmup", "20", "--max-seconds", str(args.max_seconds), "--output", str(destination)]
                completed = subprocess.run(argv, cwd=root, capture_output=True, text=True, timeout=args.max_seconds + 900)  # nosec B603
                (output / f"{repetition + 1}-{label}.log").write_text(completed.stdout + completed.stderr, encoding="utf-8")
                report_path = destination / "result.json"
                require(report_path.is_file(), "Child produced no evidence")
                raw = report_path.read_bytes()
                packet, _digest = _retained.read_json(report_path)
                row = {"repetition": repetition + 1, "variant": label, "command": argv, "report": str(report_path),
                       "report_sha256": hashlib.sha256(raw).hexdigest(), "child_exit_code": completed.returncode}
                state["runs"].append(row)
                require(completed.returncode == 0, "Child workload failed; retained incomplete admissions")
                row["verified"] = verify(packet, root, commits[label], args.count)
                configuration = {field: packet[field] for field in CONFIG}
                if reference is None:
                    reference = configuration
                require(configuration == reference, "Matched workload/hardware/configuration changed")
                (output / "pair.json").write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
                print(json.dumps({"repetition": repetition + 1, "variant": label, "verified": row["verified"]}), flush=True)
        state["status"] = "passed"
        state["matched_configuration"] = reference
        state["medians"] = {label: {metric: statistics.median(row["verified"][metric] for row in state["runs"] if row["variant"] == label)
                                          for metric in ("posting_seconds", "throughput", "p50", "p95", "p99", "client_cpu_seconds", "container_cpu_seconds", "total_cpu_seconds_per_success", "bounded_batch_read_seconds")}
                            for label in roots}
    except Exception as exc:
        state.update(status="failed", failure_type=type(exc).__name__, failure=str(exc))
    finally:
        (output / "pair.json").write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": state["status"], "output": str(output)}), flush=True)
    return 0 if state["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
