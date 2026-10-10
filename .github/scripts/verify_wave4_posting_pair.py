#!/usr/bin/env python3
"""Verify six original Wave4 posting reports offline with Python's stdlib only.

python -I verify_wave4_posting_pair.py --manifest packet/manifest.json \
    --manifest-sha256 <separately-trusted-sha256> --report fresh-proof.json

Portable manifest: schema_version="wave4-native-posting-pair-manifest-v1",
status="passed", pairs=3, count=1000, commits={baseline:..., candidate:...},
runs=[{repetition:1, variant:"baseline", report:"1-baseline/result.json",
report_sha256:..., child_exit_code:0}, ...] in BC,CB,BC order. Report paths
are relative to the manifest directory. The explicit trusted manifest digest
must come from a prior trusted channel; recomputing it from received bytes does
not authenticate that evidence. Keep the two sibling verifier scripts beside
this script. No checkout, database, Docker, network, or application imports.
Financial verification is separate from performance acceptance. Static CONFIG
equality does not establish constant dynamic host power or per-phase frequency.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import re
import statistics
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

COMMITS = {"baseline": "b7df92711d52bde1adb735e3d1ab538eb2f4e5cc",
           "candidate": "07452da8742406d2223ce522c87aee0fcd223a90"}
ORDER = ((1, "baseline"), (1, "candidate"), (2, "candidate"),
         (2, "baseline"), (3, "baseline"), (3, "candidate"))
METRICS = ("posting_seconds", "throughput", "p50", "p95", "p99", "client_cpu_seconds",
           "container_cpu_seconds", "total_cpu_seconds_per_success", "bounded_batch_read_seconds")
SCHEMA = "standalone-wave4-posting-pair-verification-v1"
_spec = importlib.util.spec_from_file_location("wave4_global_pair", Path(__file__).with_name("benchmark_global_engineering_pair.py"))
if _spec is None or _spec.loader is None:
    raise RuntimeError("Sibling global engineering verifier is absent")
_pair = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_pair)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _invalid_constant(value: str) -> None:
    raise ValueError(f"Nonfinite JSON constant: {value}")


def _json(raw: bytes) -> dict[str, Any]:
    value = json.loads(raw, object_pairs_hook=_pair._retained.unique_object, parse_constant=_invalid_constant)
    require(isinstance(value, dict), "Expected JSON object")
    return value


def _sha(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _report_path(directory: Path, relative: Any) -> Path:
    require(isinstance(relative, str) and bool(relative) and "\\" not in relative and ":" not in relative,
            "Report path must be portable and relative")
    parts = PurePosixPath(relative)
    require(not parts.is_absolute() and ".." not in parts.parts and parts.as_posix() == relative,
            "Report path escapes or is not canonical")
    path = directory.joinpath(*parts.parts).resolve()
    require(path.is_relative_to(directory), "Report symlink escapes manifest directory")
    return path


def _timestamp(value: Any) -> datetime:
    require(isinstance(value, str), "Missing run timestamp")
    result = datetime.fromisoformat(value)
    require(result.tzinfo is not None and result.utcoffset() is not None, "Naive run timestamp")
    return result.astimezone(UTC)


def _current_run_contract(packet: dict[str, Any]) -> str:
    require(packet["source_unchanged"] is True and packet["owned_container_removed"] is True,
            "Source/cleanup evidence must be explicit booleans")
    require(_sha(packet["source_sha256"]) and "failure" not in packet, "Invalid source or retained run failure")
    require(packet["runtime_role_flags"] == [False, False]
            and all(type(flag) is bool for flag in packet["runtime_role_flags"]), "Current nonowner roles required")
    require(type(packet["workers"]) is int and type(packet["repetitions"]) is int
            and packet["max_seconds"] == 1800 and type(packet["max_seconds"]) is int,
            "Different actual driver arguments")
    require(packet["cost_per_transaction"] is None, "Invented monetary cost")
    profile = packet["posting_profile"]
    require(profile["enabled"] is False and profile["raw_phase_observations"] == []
            and profile["phase_totals"] == {} and profile["statement_templates"] == []
            and profile["function_profile"]["enabled"] is False
            and profile["function_profile"]["functions"] == [], "Instrumented posting run")
    sampling = packet["resource_sampling"]
    host = sampling["host_processor_observation"]
    require(host["requested"] is True and host["platform"] == "win32" and host["status"] == "enabled"
            and host["cleanup"] == {"status": "closed", "api_status": 0}, "Host observer lifecycle failed or differs")
    container = _json(packet["container_resources_final_sample"].encode())["Container"]
    require(_sha(container), "Missing original container identity")
    previous_cpu = -1.0
    for row in sampling["raw_samples"]:
        cpu = row["client_cpu_seconds"]
        require(type(cpu) in (int, float) and math.isfinite(cpu) and cpu >= previous_cpu, "Client observation CPU decreased or invalid")
        previous_cpu = cpu
        observation = row["host_processor"]
        require(isinstance(observation, dict) and observation["status"] in ("priming", "available", "partial", "unavailable"),
                "Host observation missing or invalid")
        values = [observation[name] for name in ("processor_performance_percent", "processor_frequency_mhz")]
        require(all(value is None or type(value) in (int, float) and math.isfinite(value) and value >= 0 for value in values),
                "Host observation numeric value invalid")
        require(observation["status"] != "priming" or values == [None, None], "Priming host values must be unavailable")
        require(observation["status"] != "available" or all(value is not None for value in values), "Available host values are missing")
    return container


def _host_observations(packet: dict[str, Any]) -> dict[str, Any]:
    """Classify retained host samples; unavailable data never imply zero or AC."""
    rows = packet["resource_sampling"]["raw_samples"]
    counters: Counter[str] = Counter()
    power: Counter[str] = Counter()
    saver: Counter[str] = Counter()
    unavailable: Counter[str] = Counter()
    values: dict[str, list[int | float]] = {name: [] for name in (
        "processor_frequency_mhz", "processor_performance_percent")}
    for row in rows:
        observation = row["host_processor"]
        counters[observation["status"]] += 1
        for name, retained in values.items():
            value = observation[name]
            if type(value) in (int, float) and math.isfinite(value) and value >= 0:
                retained.append(value)
        status = observation.get("power")
        available = isinstance(status, dict) and status.get("status") == "available"
        online = status.get("ac_online") if available else None
        if type(online) is bool:
            power["ac" if online else "battery"] += 1
        else:
            power["unavailable"] += 1
            unavailable["missing_power" if status is None else
                        "power_not_available" if not available else "ac_online_not_boolean"] += 1
        flag = status.get("battery_saver_on") if available else None
        saver["on" if flag is True else "off" if flag is False else "unavailable"] += 1
    quantiles: dict[str, dict[str, Any]] = {}
    for name, retained in values.items():
        ordered = sorted(retained)
        quantiles[name] = {"available_samples": len(ordered), "unavailable_samples": len(rows) - len(ordered),
                          "min": ordered[0] if ordered else None,
                          "median": statistics.median(ordered) if ordered else None,
                          "p50": ordered[math.ceil(len(ordered) * .5) - 1] if ordered else None,
                          "p95": ordered[math.ceil(len(ordered) * .95) - 1] if ordered else None,
                          "p99": ordered[math.ceil(len(ordered) * .99) - 1] if ordered else None,
                          "max": ordered[-1] if ordered else None}
    return {"sample_count": len(rows), "counter_status_counts": dict(counters),
            "power_counts": {name: power[name] for name in ("ac", "battery", "unavailable")},
            "power_unavailable_reasons": dict(unavailable),
            "battery_saver_counts": {name: saver[name] for name in ("on", "off", "unavailable")},
            "quantiles": quantiles, "quantile_method": "nearest rank; median is arithmetic median",
            "scope": "host-wide sparse samples across setup tail, warmup, posting and reads; no per-phase or per-core binding"}


def _environment_equivalence(summaries: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {name: sum(row["host_observations"]["power_counts"][name] for row in summaries)
              for name in ("ac", "battery", "unavailable")}
    states = [name for name in ("ac", "battery") if counts[name]]
    constant = len(states) == 1 and counts["unavailable"] == 0
    return {"static_configuration_equal": True, "dynamic_host_power_constant": constant,
            "dynamic_host_power_classification": "changed" if len(states) > 1 else
                                                 "constant_observed" if constant else "unverified",
            "power_counts": counts, "observed_power_states": states,
            "dynamic_host_power_constant_scope": "retained available boolean power samples only; sparse observations do not prove uninterrupted power or equal per-core scheduling",
            "frequency_or_performance_phase_binding": "unavailable: no phase start/end timestamps or retained posting timer origin",
            "causal_attribution": "unproven; power/frequency observations do not establish the cause of measured CPU differences"}


def verify_manifest(manifest_path: Path, trusted_manifest_sha256: str) -> dict[str, Any]:
    """Bind the exact six raw byte streams, then independently verify their content."""
    require(_sha(trusted_manifest_sha256), "Explicit trusted manifest SHA256 is required")
    manifest_path = manifest_path.resolve()
    raw = manifest_path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    require(digest == trusted_manifest_sha256, "Trusted manifest SHA256 mismatch")
    manifest = _json(raw)
    require(manifest["schema_version"] == "wave4-native-posting-pair-manifest-v1"
            and manifest["status"] == "passed" and type(manifest["pairs"]) is int and manifest["pairs"] == 3
            and type(manifest["count"]) is int and manifest["count"] == 1000, "Incomplete six-run manifest")
    require(manifest["commits"] == COMMITS, "Pinned Wave4 commits differ")
    records = manifest["runs"]
    require(isinstance(records, list) and len(records) == len(ORDER), "Exactly six raw reports are required")
    summaries = []
    reference: dict[str, Any] | None = None
    source_fingerprints: dict[str, str] = {}
    paths: set[Path] = set()
    hashes: set[str] = set()
    effects: set[str] = set()
    containers: set[str] = set()
    previous_finished: datetime | None = None
    for record, (repetition, variant) in zip(records, ORDER, strict=True):
        require(type(record["repetition"]) is int and record["repetition"] == repetition
                and record["variant"] == variant, "Runs must follow BC,CB,BC order")
        require(type(record["child_exit_code"]) is int and record["child_exit_code"] == 0, "Child workload failed")
        path = _report_path(manifest_path.parent, record["report"])
        require(path not in paths, "Duplicate report path")
        paths.add(path)
        report_raw = path.read_bytes()
        report_digest = hashlib.sha256(report_raw).hexdigest()
        require(_sha(record["report_sha256"]) and report_digest == record["report_sha256"], "Raw report SHA256 mismatch")
        require(report_digest not in hashes, "Repeated raw report population")
        hashes.add(report_digest)
        packet = _json(report_raw)
        container = _current_run_contract(packet)
        require(container not in containers, "Runs must use six fresh container identities")
        containers.add(container)
        # runtime_root is retained provenance, never an import or working directory.
        verified = _pair.verify(packet, Path(packet["runtime_root"]).resolve(), COMMITS[variant], 1000)
        fingerprint = packet["source_sha256"]
        require(variant not in source_fingerprints or source_fingerprints[variant] == fingerprint,
                "Source fingerprint changed between repetitions")
        source_fingerprints[variant] = fingerprint
        configuration = {name: packet[name] for name in _pair.CONFIG}
        if reference is None:
            reference = configuration
        require(configuration == reference, "Matched workload/hardware/configuration differs across six runs")
        population = set(packet["posting"]["ordered_effect_ids"]) | set(packet["posting_warmup"]["effect_ids"])
        require(not population & effects, "Repeated financial population across runs")
        effects.update(population)
        started, finished = _timestamp(packet["started_at"]), _timestamp(packet["finished_at"])
        require(started < finished and (previous_finished is None or previous_finished <= started), "Runs overlap or timestamps differ")
        previous_finished = finished
        summaries.append({"repetition": repetition, "variant": variant, "report": record["report"],
                          "report_sha256": report_digest, "source_commit": packet["source_commit"],
                          "source_sha256": fingerprint, "container_id": container,
                          "started_at": packet["started_at"], "finished_at": packet["finished_at"],
                          "verified": verified, "host_observations": _host_observations(packet)})
    medians = {variant: {metric: statistics.median(row["verified"][metric] for row in summaries if row["variant"] == variant)
                         for metric in METRICS} for variant in COMMITS}
    changes = {metric: (medians["candidate"][metric] / medians["baseline"][metric] - 1) * 100 for metric in METRICS}
    require(all(math.isfinite(value) for value in changes.values()), "Invalid comparison metric")
    environment = _environment_equivalence(summaries)
    reasons = ["Financial byte/arithmetic verification does not certify performance acceptance."]
    if not environment["dynamic_host_power_constant"]:
        reasons.append("Dynamic host power changed or is not fully available in the retained samples.")
    for metric in ("client_cpu_seconds", "bounded_batch_read_seconds", "total_cpu_seconds_per_success"):
        if changes[metric] > 0:
            reasons.append(f"Adverse candidate change retained: {metric}.")
    return {"schema_version": SCHEMA, "status": "passed", "trusted_manifest_sha256": digest,
            "financial_verification": "passed", "performance_comparison_accepted": False,
            "performance_comparison_reasons": reasons, "environment_equivalence": environment,
            "commits": COMMITS, "source_fingerprints": source_fingerprints,
            "run_order": "BC,CB,BC", "runs": summaries, "common_configuration": reference,
            "independent_oracle_minor": {str(count): _pair._retained.minor_oracle(count) for count in (100, 1000)},
            "measured_cycles_per_variant": 3000, "warmup_cycles_per_variant": 60,
            "distinct_native_effects_including_warmup": len(effects), "distinct_container_count": len(containers),
            "medians": medians, "candidate_change_percent": changes,
            "cost_per_success_currency": None, "cross_database_digest_equality_tested": False,
            "limits": ["Trust is conditional on the independently supplied manifest SHA256; no external attestation is added.",
                       "Offline byte/arithmetic verification does not rerun or independently inspect the original databases.",
                       "Three fresh populations per source do not prove statistical causation or competitor superiority.",
                       "Native three-human cash/equity cycles include authentication; not HTTP or mixed ERP throughput.",
                       "Sampled resource windows include warmup/reads and observer overhead; measured posting CPU counters have separate boundaries; sampled peaks can miss spikes.",
                       "Per-sample Docker records omit container IDs; six distinct final IDs and financial populations prove retained freshness only.",
                       "Host counters may be explicitly unavailable; frequency/performance does not measure temperature.",
                       "Equal static configuration is separate from dynamic host power; constant observed power alone does not accept resource regressions.",
                       "Host quantiles include all sampled stages and have no exact posting/identity phase binding or causal attribution.",
                       "Adverse changes remain in the computed results; monetary cost, failover, RPO/RTO are unmeasured."]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True, help="SHA256 from a separately trusted original evidence channel")
    parser.add_argument("--report", type=Path, required=True, help="Fresh output; existing evidence is never overwritten")
    args = parser.parse_args()
    try:
        require(not args.report.exists(), "Report already exists; choose fresh output")
        report = verify_manifest(args.manifest, args.manifest_sha256)
    except (OSError, ValueError, KeyError, TypeError, OverflowError) as exc:
        report = {"schema_version": SCHEMA, "status": "failed", "failure_type": type(exc).__name__, "failure": str(exc)}
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
