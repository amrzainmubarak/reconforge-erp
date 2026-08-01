"""Reproducible synthetic benchmarks for the hosted reconciliation execution path."""

from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import time
import tracemalloc
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from reconforge.io.writers import ensure_output_dir, write_json
from reconforge.workers.postgres_reconciliation import (
    LocalDeterministicMatcherAdapter,
    ReconciliationExecutionContext,
    ReconciliationInputPartition,
)


def _compute_environment_metadata() -> dict[str, object]:
    return {
        "collected_at_utc": datetime.now(tz=UTC).isoformat().replace("+00:00", "Z"),
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "cpu_count": os.cpu_count() or 0,
        "working_directory": str(Path.cwd()),
    }


def _sha256_for_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_for_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _candidate_count_values(*, results: tuple[Mapping[str, Any], ...]) -> list[int]:
    values: list[int] = []
    for row in results:
        lineage = row.get("lineage")
        if not isinstance(lineage, dict):
            continue
        if not isinstance(row.get("left_id"), str):
            continue
        candidate_count = lineage.get("candidate_count")
        if isinstance(candidate_count, int):
            values.append(candidate_count)
    return values


def _candidate_count_stats(
    *,
    results: tuple[Mapping[str, Any], ...],
) -> tuple[int, int, float]:
    values = _candidate_count_values(results=results)
    total = sum(values)
    max_count = max(values) if values else 0
    mean = round(total / len(values), 4) if values else 0.0
    return total, max_count, mean


def _sanitize_profile_id(profile_id: str) -> str:
    sanitized = "".join(ch if ch.isalnum() or ch in "-._" else "-" for ch in profile_id)
    return sanitized.strip("-._") or "recon-benchmark"


def _to_profile_result_dict(
    *,
    profile_id: str,
    profile: ReconciliationExecutionBenchmarkProfile,
    metrics: ReconciliationExecutionBenchmarkMetrics,
    output_json: str,
    output_json_sha256: str,
    output_json_bytes: int,
) -> dict[str, object]:
    return {
        "profile_id": profile_id,
        "profile": asdict(profile),
        "output_json": output_json,
        "output_json_bytes": output_json_bytes,
        "output_json_sha256": output_json_sha256,
        "result_signature": metrics.result_signature,
        "result_count": metrics.result_count,
        "matched_rows": metrics.matched_rows,
        "exception_count": metrics.exception_count,
        "runtime_seconds": metrics.runtime_seconds,
        "peak_memory_mb": metrics.peak_memory_mb,
        "candidate_count_total": metrics.candidate_count_total,
        "candidate_count_max": metrics.candidate_count_max,
        "candidate_count_mean": metrics.candidate_count_mean,
        "cpu_time_seconds": metrics.cpu_time_seconds,
        "environment_metadata": metrics.environment_metadata,
    }


@dataclass(frozen=True)
class ReconciliationExecutionBenchmarkProfile:
    """Profile definition for one reconciliation execution benchmark run."""

    profile_id: str
    total_records: int
    partition_count: int | None = None
    partition_max_records: int = 10_000
    seed: int = 7
    amount_fractional_digits: int = 2
    streaming: bool = False


@dataclass(frozen=True)
class ReconciliationExecutionBenchmarkMetrics:
    """Measured output for one deterministic synthetic execution run."""

    total_records: int
    left_rows: int
    right_rows: int
    partition_count: int
    partition_max_records: int
    seed: int
    runtime_seconds: float
    peak_memory_mb: float
    result_count: int
    matched_rows: int
    exception_count: int
    candidate_count_total: int
    candidate_count_max: int
    candidate_count_mean: float
    result_signature: str
    cpu_time_seconds: float
    environment_metadata: dict[str, object]
    amount_fractional_digits: int = 2
    engine_used: str = "local-deterministic-partitioned"
    profile_id: str = "single"

    def to_dict(self) -> dict[str, object]:
        """Return JSON-safe benchmark fields."""

        return asdict(self)


@dataclass(frozen=True)
class ReconciliationExecutionBenchmarkSuiteProfileResult:
    """Result metadata and manifest context for one profile in a benchmark suite."""

    profile_id: str
    profile: ReconciliationExecutionBenchmarkProfile
    metrics: ReconciliationExecutionBenchmarkMetrics
    output_json: str
    output_json_sha256: str
    output_json_bytes: int

    def to_dict(self) -> dict[str, object]:
        return _to_profile_result_dict(
            profile_id=self.profile_id,
            profile=self.profile,
            metrics=self.metrics,
            output_json=self.output_json,
            output_json_sha256=self.output_json_sha256,
            output_json_bytes=self.output_json_bytes,
        )


@dataclass(frozen=True)
class ReconciliationExecutionBenchmarkSuiteResult:
    """Result artifact for a multi-profile benchmark suite."""

    profiles: tuple[ReconciliationExecutionBenchmarkSuiteProfileResult, ...]
    suite_signature: str
    output_dir: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "suite_signature": self.suite_signature,
            "profile_count": len(self.profiles),
            "suite_output_dir": self.output_dir,
            "profiles": [profile.to_dict() for profile in self.profiles],
            "environment_metadata": self.profiles[0].metrics.environment_metadata if self.profiles else {},
        }


def _synthetic_records(
    total_records: int,
    partition_count: int,
    seed: int,
    *,
    amount_fractional_digits: int = 2,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    left_count = total_records // 2
    right_count = total_records - left_count

    def record(side: str, index: int, fractional_digits: int) -> dict[str, Any]:
        amount_integer = (index % 10_000) + 1
        if fractional_digits <= 0:
            amount = f"{amount_integer}"
        else:
            fractional = (index * 7 + seed * 13) % (10**fractional_digits)
            amount = f"{amount_integer}.{fractional:0{fractional_digits}d}"
        entity = f"entity-{((index * 2_654_435_761) + seed) % partition_count:06d}"
        source_id = f"{side.lower()}-{index:09d}"
        return {
            "side": side,
            "source_id": source_id,
            "amount_decimal": amount,
            "amount_original": amount,
            "date_value": "2026-07-23",
            "attributes_json": {
                "id": source_id,
                "amount": amount,
                "date": "2026-07-23",
                "reference": f"INV-{index:09d}",
                "entity_id": entity,
            },
        }

    return (
        [record("Left", index, amount_fractional_digits) for index in range(left_count)],
        [record("Right", index, amount_fractional_digits) for index in range(right_count)],
    )


def run_reconciliation_execution_benchmark(
    total_records: int,
    *,
    partition_count: int | None = None,
    partition_max_records: int = 10_000,
    seed: int = 7,
    amount_fractional_digits: int = 2,
    output_dir: Path | str | None = None,
) -> ReconciliationExecutionBenchmarkMetrics:
    """Run a deterministic partitioned benchmark over synthetic records.

    ``total_records`` counts both sides. The default partition count keeps the
    expected combined partition below the configured bound; callers may choose
    a smaller count to exercise the fail-closed limit.
    """

    if not 2 <= int(total_records) <= 2_000_000:
        raise ValueError("total_records must be between 2 and 2000000.")
    if isinstance(seed, bool):
        raise ValueError("seed must be an integer.")
    if not 0 <= int(amount_fractional_digits) <= 18:
        raise ValueError("amount_fractional_digits must be between 0 and 18.")
    selected_partitions = partition_count or max(1, math.ceil(int(total_records) / 5_000))
    if not 1 <= int(selected_partitions) <= 100_000:
        raise ValueError("partition_count must be between 1 and 100000.")
    if not 1 <= int(partition_max_records) <= 100_000:
        raise ValueError("partition_max_records must be between 1 and 100000.")
    left_records, right_records = _synthetic_records(
        int(total_records),
        int(selected_partitions),
        int(seed),
        amount_fractional_digits=int(amount_fractional_digits),
    )
    adapter = LocalDeterministicMatcherAdapter()
    started_cpu = time.process_time()
    try:
        tracemalloc.start()
        started = time.perf_counter()
        output = adapter(
            ReconciliationExecutionContext(
                run={
                    "rule_json": {
                        "partition_fields": ["entity_id"],
                        "partition_max_records": int(partition_max_records),
                        "amount_tolerance": "0",
                    }
                },
                left_inputs=tuple(left_records),
                right_inputs=tuple(right_records),
                heartbeat=lambda _: {},
                cancellation_requested=lambda: False,
            )
        )
        runtime = time.perf_counter() - started
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
    finally:
        adapter.close()
        if tracemalloc.is_tracing():
            tracemalloc.stop()

    payload = {"results": list(output.results), "exceptions": list(output.exceptions)}
    signature = hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()
    candidate_count_total, candidate_count_max, candidate_count_mean = _candidate_count_stats(
        results=tuple(output.results)
    )
    metrics = ReconciliationExecutionBenchmarkMetrics(
        total_records=int(total_records),
        left_rows=len(left_records),
        right_rows=len(right_records),
        partition_count=int(selected_partitions),
        partition_max_records=int(partition_max_records),
        seed=int(seed),
        runtime_seconds=round(runtime, 4),
        peak_memory_mb=round(peak / 1_048_576, 2),
        result_count=len(output.results),
        matched_rows=sum(str(item.get("status", "")) == "Matched" for item in output.results),
        exception_count=len(output.exceptions),
        candidate_count_total=candidate_count_total,
        candidate_count_max=candidate_count_max,
        candidate_count_mean=candidate_count_mean,
        result_signature=signature,
        cpu_time_seconds=round(time.process_time() - started_cpu, 4),
        environment_metadata=_compute_environment_metadata(),
        amount_fractional_digits=int(amount_fractional_digits),
        profile_id="single",
    )
    _write_execution_metrics(metrics, output_dir)
    return metrics


def run_reconciliation_execution_streaming_benchmark(
    total_records: int,
    *,
    partition_count: int | None = None,
    partition_max_records: int = 10_000,
    seed: int = 7,
    amount_fractional_digits: int = 2,
    output_dir: Path | str | None = None,
) -> ReconciliationExecutionBenchmarkMetrics:
    """Benchmark lazy synthetic partition input without materializing a manifest.

    This measures the adapter's partition iterator and deterministic matching
    path with one generated partition resident at a time. It is still a local
    algorithm benchmark; it does not claim PostgreSQL network or deployment
    performance.
    """

    if not 2 <= int(total_records) <= 2_000_000:
        raise ValueError("total_records must be between 2 and 2000000.")
    if isinstance(seed, bool):
        raise ValueError("seed must be an integer.")
    if not 0 <= int(amount_fractional_digits) <= 18:
        raise ValueError("amount_fractional_digits must be between 0 and 18.")
    selected_partitions = partition_count or max(1, math.ceil(int(total_records) / 5_000))
    if not 1 <= int(selected_partitions) <= 100_000:
        raise ValueError("partition_count must be between 1 and 100000.")
    if not 1 <= int(partition_max_records) <= 100_000:
        raise ValueError("partition_max_records must be between 1 and 100000.")
    left_count = int(total_records) // 2
    right_count = int(total_records) - left_count

    def make_record(side: str, index: int, entity: str) -> dict[str, Any]:
        amount_integer = (index % 10_000) + 1
        if int(amount_fractional_digits) <= 0:
            amount = f"{amount_integer}"
        else:
            fractional = (index * 7 + int(seed) * 13) % (10 ** int(amount_fractional_digits))
            amount = f"{amount_integer}.{fractional:0{int(amount_fractional_digits)}d}"
        source_id = f"{side.lower()}-{index:09d}"
        return {
            "side": side,
            "source_id": source_id,
            "amount_decimal": amount,
            "amount_original": amount,
            "date_value": "2026-07-23",
            "attributes_json": {
                "id": source_id,
                "amount": amount,
                "date": "2026-07-23",
                "reference": f"INV-{index:09d}",
                "entity_id": entity,
            },
        }

    partition_keys = [
        (
            hashlib.sha256(
                json.dumps([f"entity-{index:06d}"], ensure_ascii=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
            index,
        )
        for index in range(int(selected_partitions))
    ]
    partition_keys.sort()

    def supplier() -> Any:
        for _, partition_index in partition_keys:
            entity = f"entity-{((partition_index + int(seed)) % int(selected_partitions)):06d}"
            left_records = tuple(
                make_record("Left", index, entity)
                for index in range(partition_index, left_count, int(selected_partitions))
            )
            right_records = tuple(
                make_record("Right", index, entity)
                for index in range(partition_index, right_count, int(selected_partitions))
            )
            partition_key = hashlib.sha256(
                json.dumps([entity], ensure_ascii=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            yield ReconciliationInputPartition(partition_key, left_records, right_records)

    adapter = LocalDeterministicMatcherAdapter()
    result_count = 0
    matched_rows = 0
    exception_count = 0
    signature = hashlib.sha256()
    candidate_count_total = 0
    candidate_count_max = 0
    candidate_count_values: list[int] = []
    started_cpu = time.process_time()
    try:
        tracemalloc.start()
        started = time.perf_counter()
        for partition in adapter.iter_partition_results(
            ReconciliationExecutionContext(
                run={
                    "rule_json": {
                        "partition_fields": ["entity_id"],
                        "partition_max_records": int(partition_max_records),
                        "amount_tolerance": "0",
                    }
                },
                left_inputs=(),
                right_inputs=(),
                heartbeat=lambda _: {},
                cancellation_requested=lambda: False,
                partition_supplier=supplier,
            )
        ):
            payload = {
                "partition_key": partition.partition_key,
                "results": list(partition.results),
                "exceptions": list(partition.exceptions),
            }
            signature.update(
                json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str).encode(
                    "utf-8"
                )
            )
            partition_candidate_values = _candidate_count_values(results=tuple(partition.results))
            partition_candidate_total = sum(partition_candidate_values)
            partition_candidate_max = max(partition_candidate_values) if partition_candidate_values else 0
            candidate_count_total += partition_candidate_total
            candidate_count_max = max(candidate_count_max, partition_candidate_max)
            candidate_count_values.extend(partition_candidate_values)
            result_count += len(partition.results)
            matched_rows += sum(str(item.get("status", "")) == "Matched" for item in partition.results)
            exception_count += len(partition.exceptions)
        runtime = time.perf_counter() - started
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
    finally:
        adapter.close()
        if tracemalloc.is_tracing():
            tracemalloc.stop()
    candidate_count_mean = (
        round(sum(candidate_count_values) / len(candidate_count_values), 4) if candidate_count_values else 0.0
    )
    metrics = ReconciliationExecutionBenchmarkMetrics(
        total_records=int(total_records),
        left_rows=left_count,
        right_rows=right_count,
        partition_count=int(selected_partitions),
        partition_max_records=int(partition_max_records),
        seed=int(seed),
        runtime_seconds=round(runtime, 4),
        peak_memory_mb=round(peak / 1_048_576, 2),
        result_count=result_count,
        matched_rows=matched_rows,
        exception_count=exception_count,
        candidate_count_total=candidate_count_total,
        candidate_count_max=candidate_count_max,
        candidate_count_mean=candidate_count_mean,
        result_signature=signature.hexdigest(),
        cpu_time_seconds=round(time.process_time() - started_cpu, 4),
        environment_metadata=_compute_environment_metadata(),
        amount_fractional_digits=int(amount_fractional_digits),
        engine_used="local-deterministic-partitioned-streaming",
        profile_id="single-streaming",
    )
    _write_execution_metrics(metrics, output_dir)
    return metrics


def _write_execution_metrics(
    metrics: ReconciliationExecutionBenchmarkMetrics,
    output_dir: Path | str | None,
) -> None:
    """Write one benchmark result in machine- and human-readable formats."""

    if output_dir is None:
        return
    target = ensure_output_dir(output_dir)
    write_json(metrics.to_dict(), target, "reconciliation-execution")
    (target / "reconciliation-execution.md").write_text(
        "# Reconciliation Execution Benchmark\n\n"
        "| Metric | Value |\n| --- | --- |\n"
        + "\n".join(f"| {key} | {value} |" for key, value in metrics.to_dict().items())
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


def run_reconciliation_execution_benchmark_suite(
    profiles: tuple[ReconciliationExecutionBenchmarkProfile, ...] = (
        ReconciliationExecutionBenchmarkProfile(profile_id="reconciliation-10k", total_records=10_000),
        ReconciliationExecutionBenchmarkProfile(profile_id="reconciliation-100k", total_records=100_000),
    ),
    *,
    output_dir: Path | str | None = None,
) -> ReconciliationExecutionBenchmarkSuiteResult:
    """Run a reproducible benchmark suite across multiple profiles."""

    if not profiles:
        raise ValueError("At least one benchmark profile is required.")
    suite_profiles: list[ReconciliationExecutionBenchmarkSuiteProfileResult] = []
    base_output = ensure_output_dir(output_dir) if output_dir is not None else None
    for profile in profiles:
        safe_profile_id = _sanitize_profile_id(profile.profile_id)
        profile_output_dir: Path | None = None
        if base_output is not None:
            profile_output_dir = base_output / safe_profile_id
        if profile.streaming:
            metrics = run_reconciliation_execution_streaming_benchmark(
                total_records=profile.total_records,
                partition_count=profile.partition_count,
                partition_max_records=profile.partition_max_records,
                seed=profile.seed,
                amount_fractional_digits=profile.amount_fractional_digits,
                output_dir=profile_output_dir,
            )
        else:
            metrics = run_reconciliation_execution_benchmark(
                total_records=profile.total_records,
                partition_count=profile.partition_count,
                partition_max_records=profile.partition_max_records,
                seed=profile.seed,
                amount_fractional_digits=profile.amount_fractional_digits,
                output_dir=profile_output_dir,
            )
        if profile_output_dir is None:
            output_json = "reconciliation-execution.json"
            output_json_bytes = 0
            output_json_sha256 = ""
        else:
            output_json_path = profile_output_dir / "reconciliation-execution.json"
            output_json = (
                output_json_path.relative_to(base_output).as_posix()
                if base_output is not None
                else output_json_path.as_posix()
            )
            output_json_bytes = output_json_path.stat().st_size
            output_json_sha256 = _sha256_for_file(output_json_path)
        suite_profiles.append(
            ReconciliationExecutionBenchmarkSuiteProfileResult(
                profile_id=profile.profile_id,
                profile=profile,
                metrics=metrics,
                output_json=output_json,
                output_json_sha256=output_json_sha256,
                output_json_bytes=output_json_bytes,
            )
        )
    suite_signature = _sha256_for_text(
        json.dumps(
            {
                "profiles": [
                    {
                        "profile_id": profile_result.profile_id,
                        "result_signature": profile_result.metrics.result_signature,
                        "output_json_sha256": profile_result.output_json_sha256,
                    }
                    for profile_result in suite_profiles
                ]
            },
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    suite_payload = {
        "suite_signature": "",
        "profile_count": len(suite_profiles),
        "profiles": [profile_result.to_dict() for profile_result in suite_profiles],
        "environment_metadata": suite_profiles[0].metrics.environment_metadata if suite_profiles else {},
    }
    suite_payload["suite_signature"] = suite_signature
    suite_result = ReconciliationExecutionBenchmarkSuiteResult(
        profiles=tuple(suite_profiles),
        suite_signature=suite_signature,
        output_dir=str(base_output) if base_output is not None else None,
    )
    if base_output is not None:
        suite_payload["suite_signature"] = suite_result.suite_signature
        write_json(suite_payload, base_output, "reconciliation-execution-benchmark-suite")
        suite_rows = (
            f"| {profile_result.profile_id} | {profile_result.metrics.result_signature[:16]} | "
            f"{profile_result.metrics.runtime_seconds} | {profile_result.metrics.peak_memory_mb} | "
            f"{profile_result.metrics.candidate_count_max} | {profile_result.metrics.candidate_count_total} |"
            for profile_result in suite_profiles
        )
        suite_summary = "\n".join(
            (
                "| Profile | Signature | Runtime (s) | Peak MB | Candidate max | Candidate count total |",
                "| --- | --- | --- | --- | --- | --- |",
                *suite_rows,
            )
        )
        (base_output / "reconciliation-execution-benchmark-suite.md").write_text(
            "# Reconciliation Execution Benchmark Suite\n\n" + suite_summary + "\n",
            encoding="utf-8",
            newline="\n",
        )
    return suite_result


def assert_reconciliation_execution_regression(
    baseline: ReconciliationExecutionBenchmarkSuiteResult | dict[str, ReconciliationExecutionBenchmarkMetrics],
    candidate: ReconciliationExecutionBenchmarkSuiteResult | dict[str, ReconciliationExecutionBenchmarkMetrics],
    *,
    max_runtime_regression_ratio: float = 1.25,
    max_cpu_time_regression_ratio: float = 1.25,
    max_peak_memory_mb_increase: float = 64.0,
    allow_signature_change: bool = False,
) -> None:
    """Assert that candidate benchmark metrics are not regressed beyond limits."""

    if max_runtime_regression_ratio <= 1:
        raise ValueError("max_runtime_regression_ratio must be greater than 1.")
    if max_cpu_time_regression_ratio <= 1:
        raise ValueError("max_cpu_time_regression_ratio must be greater than 1.")
    if max_peak_memory_mb_increase < 0:
        raise ValueError("max_peak_memory_mb_increase must be zero or greater.")

    baseline_map = _coerce_suite_to_map(baseline)
    candidate_map = _coerce_suite_to_map(candidate)
    if set(baseline_map.keys()) != set(candidate_map.keys()):
        missing = sorted(set(baseline_map.keys()) - set(candidate_map.keys()))
        extra = sorted(set(candidate_map.keys()) - set(baseline_map.keys()))
        raise AssertionError(f"Profile ids differ. Missing in candidate: {missing}; extra in candidate: {extra}.")
    for profile_id in sorted(baseline_map.keys()):
        base = baseline_map[profile_id]
        observed = candidate_map[profile_id]
        _assert_reconciliation_execution_profile_regression(
            profile_id=profile_id,
            baseline=base,
            candidate=observed,
            max_runtime_regression_ratio=max_runtime_regression_ratio,
            max_cpu_time_regression_ratio=max_cpu_time_regression_ratio,
            max_peak_memory_mb_increase=max_peak_memory_mb_increase,
            allow_signature_change=allow_signature_change,
        )


def _coerce_suite_to_map(
    results: ReconciliationExecutionBenchmarkSuiteResult | dict[str, ReconciliationExecutionBenchmarkMetrics],
) -> dict[str, ReconciliationExecutionBenchmarkMetrics]:
    if isinstance(results, ReconciliationExecutionBenchmarkSuiteResult):
        return {profile_result.profile_id: profile_result.metrics for profile_result in results.profiles}
    return dict(results)


def _assert_reconciliation_execution_profile_regression(
    *,
    profile_id: str,
    baseline: ReconciliationExecutionBenchmarkMetrics,
    candidate: ReconciliationExecutionBenchmarkMetrics,
    max_runtime_regression_ratio: float,
    max_cpu_time_regression_ratio: float,
    max_peak_memory_mb_increase: float,
    allow_signature_change: bool = False,
) -> None:
    if baseline.result_count != candidate.result_count:
        raise AssertionError(
            f"{profile_id}: result_count changed from {baseline.result_count} to {candidate.result_count}."
        )
    if baseline.matched_rows != candidate.matched_rows:
        raise AssertionError(
            f"{profile_id}: matched_rows changed from {baseline.matched_rows} to {candidate.matched_rows}."
        )
    if baseline.exception_count != candidate.exception_count:
        raise AssertionError(
            f"{profile_id}: exception_count changed from {baseline.exception_count} to {candidate.exception_count}."
        )
    if baseline.candidate_count_total != candidate.candidate_count_total:
        raise AssertionError(
            f"{profile_id}: candidate_count_total changed from {baseline.candidate_count_total} "
            f"to {candidate.candidate_count_total}."
        )
    if baseline.candidate_count_max != candidate.candidate_count_max:
        raise AssertionError(
            f"{profile_id}: candidate_count_max changed from {baseline.candidate_count_max} "
            f"to {candidate.candidate_count_max}."
        )
    if baseline.candidate_count_mean != candidate.candidate_count_mean:
        raise AssertionError(
            f"{profile_id}: candidate_count_mean changed from {baseline.candidate_count_mean} "
            f"to {candidate.candidate_count_mean}."
        )
    if baseline.profile_id != candidate.profile_id:
        raise AssertionError(f"{profile_id}: profile_id changed from {baseline.profile_id} to {candidate.profile_id}.")

    runtime_growth = candidate.runtime_seconds / max(1e-12, baseline.runtime_seconds)
    if runtime_growth > max_runtime_regression_ratio:
        raise AssertionError(
            f"{profile_id}: runtime regression ratio {runtime_growth:.3f} exceeds allowed {max_runtime_regression_ratio:.3f}."
        )
    cpu_growth = candidate.cpu_time_seconds / max(1e-12, baseline.cpu_time_seconds)
    if cpu_growth > max_cpu_time_regression_ratio:
        raise AssertionError(
            f"{profile_id}: CPU growth ratio {cpu_growth:.3f} exceeds allowed {max_cpu_time_regression_ratio:.3f}."
        )
    memory_growth = candidate.peak_memory_mb - baseline.peak_memory_mb
    if memory_growth > max_peak_memory_mb_increase:
        raise AssertionError(
            f"{profile_id}: peak memory increase {memory_growth:.2f} MB exceeds {max_peak_memory_mb_increase:.2f} MB."
        )
    if not allow_signature_change and baseline.result_signature != candidate.result_signature:
        raise AssertionError(
            f"{profile_id}: result_signature changed from {baseline.result_signature} to {candidate.result_signature}."
        )
