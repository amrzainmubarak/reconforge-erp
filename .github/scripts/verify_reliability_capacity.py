"""Run a bounded local reliability capacity and backlog-recovery exercise."""

from __future__ import annotations

import argparse
import json
import platform
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter_ns
from typing import Any

from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.db import connect, run_migrations
from reconforge.reliability import AlertState, MetricKey, evaluate_alerts
from reconforge.reliability_sources import HttpReliabilityWindow, SQLiteReliabilityCollector, process_memory_mib

REQUESTS = 1_000
QUEUED_JOBS = 1_000


def run_drill() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="reconforge-capacity-") as temporary:
        database = Path(temporary) / "capacity.db"
        run_migrations(database)
        window = HttpReliabilityWindow(capacity=REQUESTS)
        client = TestClient(create_api_app(database, reliability_window=window))
        api_started = perf_counter_ns()
        statuses = [client.get("/api/v1/health").status_code for _ in range(REQUESTS)]
        api_wall_ms = (perf_counter_ns() - api_started) // 1_000_000
        connection = connect(database)
        created_at = "2026-07-30T10:00:00Z"
        rows = [
            (
                f"job-{index:04d}", 1, 1, "queued", "capacity", f"key-{index:04d}", "tenant",
                "workspace", "", "a" * 64, "b" * 64, "worker/1", 0, 1, "", 0, 1, "",
                created_at, created_at, "", "", None, "", "",
            )
            for index in range(QUEUED_JOBS)
        ]
        connection.executemany(
            "INSERT INTO durable_jobs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
        connection.commit()
        collector = SQLiteReliabilityCollector(
            connection, http_window=window, dependency_probes=(lambda: True,), memory_mib=process_memory_mib
        )
        query_started = perf_counter_ns()
        overloaded = collector.collect(observed_at=datetime(2026, 7, 30, 10, 10, tzinfo=UTC))
        query_ms = (perf_counter_ns() - query_started) // 1_000_000
        overloaded_alerts = {result.policy_id: result for result in evaluate_alerts(overloaded.values)}
        connection.execute(
            "UPDATE durable_jobs SET status = 'completed', completed_units = total_units, completed_at = updated_at"
        )
        connection.commit()
        recovered = collector.collect(observed_at=datetime(2026, 7, 30, 10, 11, tzinfo=UTC))
        recovered_alerts = {result.policy_id: result for result in evaluate_alerts(recovered.values)}
        connection.close()
    return {
        "schema_version": 1,
        "profile": "local-synthetic-capacity-and-backlog-recovery",
        "runtime": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "logical_cpus": __import__("os").cpu_count() or 1,
        },
        "measurements": {
            "requests": REQUESTS,
            "api_wall_milliseconds": api_wall_ms,
            "api_p95_milliseconds": overloaded.values[MetricKey.HTTP_P95_MS],
            "api_error_basis_points": overloaded.values[MetricKey.HTTP_ERROR_BPS],
            "queued_jobs": overloaded.values[MetricKey.QUEUE_DEPTH],
            "job_aggregate_query_milliseconds": query_ms,
            "process_memory_mebibytes": overloaded.values[MetricKey.PROCESS_MEMORY_MIB],
        },
        "checks": {
            "all_api_requests_succeeded": all(status == 200 for status in statuses),
            "api_window_complete": len(statuses) == REQUESTS,
            "backlog_became_critical": overloaded_alerts["job-backlog"].state is AlertState.CRITICAL,
            "backlog_recovered_to_normal": recovered_alerts["job-backlog"].state is AlertState.NORMAL,
            "oldest_age_recovered_to_zero": recovered.values[MetricKey.OLDEST_JOB_AGE_SECONDS] == 0,
            "job_query_under_five_seconds": query_ms < 5_000,
            "all_sources_available": not overloaded.unavailable_sources and not recovered.unavailable_sources,
        },
        "limitations": [
            "single_process_in_memory_http_transport",
            "synthetic_local_sqlite_data",
            "single_run_not_production_slo",
            "no_soak_or_distributed_capacity_claim",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run_drill()
    if not all(report["checks"].values()):
        raise SystemExit("Reliability capacity drill failed")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
