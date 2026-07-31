"""Run a local, synthetic reliability failure-and-recovery exercise."""

from __future__ import annotations

import argparse
import json
import logging
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from reconforge.db import connect, run_migrations
from reconforge.observability import ObservabilityRuntime, TelemetryCorrelationFilter, telemetry_request_context
from reconforge.reliability import AlertState, MetricKey, evaluate_alerts
from reconforge.reliability_sources import HttpReliabilityWindow, SQLiteReliabilityCollector


def _states(values: dict[MetricKey, int]) -> dict[str, str]:
    return {result.policy_id: result.state.value for result in evaluate_alerts(values)}


def run_drill() -> dict[str, Any]:
    metric_reader = InMemoryMetricReader()
    span_exporter = InMemorySpanExporter()
    runtime = ObservabilityRuntime.create(metric_reader=metric_reader, span_exporter=span_exporter)
    source_state = {"dependencies_healthy": False, "memory_mib": 3_072}
    http_window = HttpReliabilityWindow()
    http_window.record(status_code=200, duration_ms=10)
    with tempfile.TemporaryDirectory(prefix="reconforge-reliability-") as temporary:
        database = Path(temporary) / "drill.db"
        run_migrations(database)
        connection = connect(database)
        collector = SQLiteReliabilityCollector(
            connection,
            http_window=http_window,
            dependency_probes=(
                lambda: bool(source_state["dependencies_healthy"]),
                lambda: bool(source_state["dependencies_healthy"]),
            ),
            memory_mib=lambda: int(source_state["memory_mib"]),
        )
        observed_at = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
        degraded = dict(collector.collect(observed_at=observed_at).values)
        source_state.update(dependencies_healthy=True, memory_mib=0)
        healthy = dict(collector.collect(observed_at=observed_at).values)
        connection.close()
    for key, value in degraded.items():
        runtime.record_reliability_measurement(key, value)
    for key, value in healthy.items():
        runtime.record_reliability_measurement(key, value)
    record = logging.LogRecord("reconforge.reliability", logging.INFO, __file__, 1, "dependency-recovered", (), None)
    with telemetry_request_context("reliability-drill-1"), runtime.span(
        "reconforge.reliability.recovery", {"reconforge.operation": "dependency-recovery"}
    ):
        TelemetryCorrelationFilter().filter(record)
    degraded_states = _states(degraded)
    recovered_states = _states(healthy)
    metric_data = metric_reader.get_metrics_data()
    if metric_data is None:
        raise RuntimeError("OpenTelemetry returned no metric data")
    metric_names = sorted(
        metric.name
        for resource in metric_data.resource_metrics
        for scope in resource.scope_metrics
        for metric in scope.metrics
    )
    return {
        "schema_version": 1,
        "policy_version": "reconforge-reliability-policy-v1",
        "profile": "local-synthetic-single-process",
        "failure": degraded_states,
        "recovery": recovered_states,
        "checks": {
            "dependency_became_critical": degraded_states["dependency-readiness"] == AlertState.CRITICAL,
            "capacity_became_critical": degraded_states["process-memory"] == AlertState.CRITICAL,
            "all_signals_recovered": all(state == AlertState.NORMAL for state in recovered_states.values()),
            "all_metrics_exported": len(metric_names) == len(MetricKey),
            "trace_exported": len(span_exporter.get_finished_spans()) == 1,
            "log_correlated": bool(record.reconforge_request_id and record.reconforge_trace_id),  # type: ignore[attr-defined]
        },
        "metric_names": metric_names,
        "limitations": [
            "synthetic_local_process_only",
            "no_external_collector_or_alert_manager",
            "no_production_slo_claim",
            "no_ha_or_external_assurance_claim",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run_drill()
    if not all(report["checks"].values()):
        raise SystemExit("reliability drill failed")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
