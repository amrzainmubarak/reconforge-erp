"""Reproducible synthetic benchmarks for the hosted reconciliation execution path."""

from __future__ import annotations

import hashlib
import json
import math
import time
import tracemalloc
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from reconforge.io.writers import ensure_output_dir, write_json
from reconforge.workers.postgres_reconciliation import (
    LocalDeterministicMatcherAdapter,
    ReconciliationExecutionContext,
    ReconciliationInputPartition,
)


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
    result_signature: str
    amount_fractional_digits: int = 2
    engine_used: str = "local-deterministic-partitioned"

    def to_dict(self) -> dict[str, object]:
        """Return JSON-safe benchmark fields."""

        return asdict(self)


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
    left_records, right_records = _synthetic_records(
        int(total_records),
        int(selected_partitions),
        int(seed),
        amount_fractional_digits=int(amount_fractional_digits),
    )
    adapter = LocalDeterministicMatcherAdapter()
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
        result_signature=signature,
        amount_fractional_digits=int(amount_fractional_digits),
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
        + "\n".join(f"| {key} | {value} |" for key, value in metrics.to_dict().items()),
        encoding="utf-8",
    )


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
            fractional = (index * 7 + int(seed) * 13) % (10**int(amount_fractional_digits))
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
                json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
            )
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
        result_signature=signature.hexdigest(),
        amount_fractional_digits=int(amount_fractional_digits),
        engine_used="local-deterministic-partitioned-streaming",
    )
    _write_execution_metrics(metrics, output_dir)
    return metrics
