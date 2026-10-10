"""Alternating snapshot reads against the original dimension-query algorithm."""
from __future__ import annotations

import statistics
import time
import tracemalloc
from collections.abc import Mapping
from typing import Any

from reconforge.benchmark.enterprise_financial import MeasuredConnection
from reconforge.domain.finance_posting import make_entry_snapshot, validation_digest
from reconforge.infrastructure.finance_policy_store import FinancePolicyStore
from reconforge.infrastructure.postgres_finance_posting import posting_snapshot, records


def legacy_snapshot(connection: Any, tenant_id: str, entry: Mapping[str, Any]) -> dict[str, Any]:
    """Frozen pre-optimization algorithm; only benchmark callers may use it."""
    FinancePolicyStore(connection, tenant_id=tenant_id).entry(entry)
    lines = records(connection.execute(
        "SELECT id,line_number,account_id,description,debit_minor,credit_minor FROM reconforge.finance_entry_lines WHERE tenant_id=%s AND entry_id=%s ORDER BY line_number",
        (tenant_id, entry["id"])))
    for line in lines:
        dimensions = records(connection.execute(
            "SELECT dimension_id,dimension_value_id FROM reconforge.finance_entry_line_dimensions WHERE tenant_id=%s AND entry_line_id=%s ORDER BY dimension_id",
            (tenant_id, line["id"])))
        line["dimensions"] = {row["dimension_id"]: row["dimension_value_id"] for row in dimensions}
    return make_entry_snapshot(entry, lines)


def measure_snapshot_reads(connection: Any, tenant_id: str, entry: Mapping[str, Any], *,
                           expected_line_count: int, expected_total_minor: int, expected_validation_digest: str,
                           repetitions: int = 3, evidence_sink: dict[str, Any] | None = None) -> dict[str, Any]:
    """Keep the financial policy, source entry, scope and warmed cache identical."""
    if (type(repetitions) is not int or not 1 <= repetitions <= 10
            or type(expected_line_count) is not int or not 2 <= expected_line_count <= 1000
            or type(expected_total_minor) is not int or expected_total_minor <= 0):
        raise ValueError("A bounded exact snapshot profile is required")
    measured = MeasuredConnection(connection)
    readers = {"per_line_baseline": legacy_snapshot, "joined_snapshot": posting_snapshot}
    samples: dict[str, list[dict[str, Any]]] = {name: [] for name in readers}
    evidence = evidence_sink if evidence_sink is not None else {}
    evidence.update(status="running", measurement_scope="native posting snapshot reads on one authenticated scoped connection; no HTTP, identity or posting throughput claim",
                    cache_policy="both warmed; alternating modes", line_count=expected_line_count,
                    expected_total_minor=str(expected_total_minor), expected_validation_digest=expected_validation_digest,
                    request_unit="one complete reviewed journal snapshot", samples=samples)
    try:
        for reader in readers.values():
            if validation_digest(reader(measured, tenant_id, entry)) != expected_validation_digest:
                raise AssertionError("Warm snapshot differs from the independently reviewed journal seal")
        for repetition in range(repetitions):
            modes = tuple(readers) if repetition % 2 == 0 else tuple(reversed(readers))
            for mode in modes:
                sample: dict[str, Any] = {"repetition": repetition, "status": "running"}
                samples[mode].append(sample)
                measured.execute_calls = 0
                started, cpu_started = time.perf_counter(), time.process_time()
                tracemalloc.start()
                try:
                    snapshot = readers[mode](measured, tenant_id, entry)
                    digest = validation_digest(snapshot)
                    debit = sum(line["debit_minor"] for line in snapshot["lines"])
                    credit = sum(line["credit_minor"] for line in snapshot["lines"])
                    if (len(snapshot["lines"]) != expected_line_count or debit != expected_total_minor
                            or credit != expected_total_minor or digest != expected_validation_digest):
                        raise AssertionError("Snapshot differs from independent line totals or reviewed digest")
                    sample.update(status="complete", validation_digest=digest, debit_minor=str(debit), credit_minor=str(credit),
                                  lines=len(snapshot["lines"]), dimension_links=sum(len(line["dimensions"]) for line in snapshot["lines"]))
                except Exception as exc:
                    sample.update(status="failed", failure={"exception_type": type(exc).__name__})
                    raise
                finally:
                    _, peak = tracemalloc.get_traced_memory()
                    tracemalloc.stop()
                    sample.update(seconds=time.perf_counter() - started, client_process_cpu_seconds=time.process_time() - cpu_started,
                                  client_execute_calls=measured.execute_calls, peak_python_allocated_bytes=peak)
        before = statistics.median(sample["seconds"] for sample in samples["per_line_baseline"])
        after = statistics.median(sample["seconds"] for sample in samples["joined_snapshot"])
        evidence.update(status="passed", median_seconds_baseline=before, median_seconds_optimized=after, measured_speedup=before / after)
    except Exception as exc:
        evidence.update(status="failed", failure={"exception_type": type(exc).__name__})
        raise
    return evidence
