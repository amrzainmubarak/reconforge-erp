from __future__ import annotations

import logging
import sqlite3
import threading
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.application.jobs import DurableJobApplicationService, DurableJobWorkerService, JobSubmission
from reconforge.db import connect, run_migrations
from reconforge.domain.jobs import JobOutputManifest
from reconforge.infrastructure.sqlite_jobs import SQLiteDurableJobRepository
from reconforge.observability import (
    ObservabilityConfigurationError,
    ObservabilityRuntime,
    OTLPHTTPConfiguration,
    TelemetryCorrelationFilter,
    create_otlp_http_runtime,
    safe_attributes,
    telemetry_request_context,
)
from reconforge.reliability import MetricKey

otel_metrics_export = pytest.importorskip(
    "opentelemetry.sdk.metrics.export", reason="observability extra is optional"
)
otel_trace_export = pytest.importorskip(
    "opentelemetry.sdk.trace.export.in_memory_span_exporter",
    reason="observability extra is optional",
)
InMemoryMetricReader = otel_metrics_export.InMemoryMetricReader
InMemorySpanExporter = otel_trace_export.InMemorySpanExporter


def test_opentelemetry_api_trace_and_metrics_are_safe_and_correlated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "observability.db"
    run_migrations(db_path)
    spans = InMemorySpanExporter()
    metrics = InMemoryMetricReader()
    monkeypatch.setenv("OTEL_RESOURCE_ATTRIBUTES", "tenant-id=safe-tenant-demo,amount=100")
    monkeypatch.setenv("OTEL_TRACES_EXPORTER", "otlp")
    runtime = ObservabilityRuntime.create(span_exporter=spans, metric_reader=metrics)
    client = TestClient(create_api_app(db_path, observability=runtime))

    response = client.get("/api/v1/health", headers={"X-Request-ID": "request-safe-1"})

    assert response.status_code == 200
    finished = spans.get_finished_spans()
    assert len(finished) == 1
    attributes = dict(finished[0].attributes or {})
    assert attributes["http.request.method"] == "GET"
    assert attributes["http.route"] == "/api/v1/health"
    assert attributes["http.response.status_code"] == 200
    assert not ({"tenant_id", "workspace_id", "amount", "currency", "record"} & set(attributes))
    assert dict(finished[0].resource.attributes) == {"service.name": "reconforge-api"}
    metric_names = {metric.name for resource in metrics.get_metrics_data().resource_metrics for scope in resource.scope_metrics for metric in scope.metrics}
    assert {"reconforge.http.server.duration", "reconforge.http.server.requests"} <= metric_names


def test_telemetry_policy_rejects_sensitive_high_cardinality_or_financial_attributes() -> None:
    for attributes in (
        {"tenant_id": "tenant-a"},
        {"amount": 12},
        {"http.route": "/records/actual-secret-id" * 20},
        {"reconforge.result": 1.25},
    ):
        with pytest.raises(ObservabilityConfigurationError):
            safe_attributes(attributes)


def test_log_filter_correlates_without_exposing_message_data() -> None:
    record = logging.LogRecord("reconforge.test", logging.INFO, __file__, 1, "safe-event", (), None)
    with telemetry_request_context("request-1"):
        assert TelemetryCorrelationFilter().filter(record)
    assert record.reconforge_request_id == "request-1"  # type: ignore[attr-defined]
    assert record.reconforge_telemetry_policy == "reconforge-telemetry-attributes-v1"  # type: ignore[attr-defined]
    assert record.getMessage() == "safe-event"


def test_observability_is_disabled_and_network_free_by_default(tmp_path: Path) -> None:
    db_path = tmp_path / "disabled.db"
    run_migrations(db_path)
    app = create_api_app(db_path)
    assert app.state.observability == ObservabilityRuntime.disabled()
    assert TestClient(app).get("/api/v1/health").status_code == 200


def test_durable_job_spans_exclude_tenant_workspace_actor_and_job_identity(tmp_path: Path) -> None:
    db_path = tmp_path / "jobs.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    exporter = InMemorySpanExporter()
    metrics = InMemoryMetricReader()
    runtime = ObservabilityRuntime.create(span_exporter=exporter, metric_reader=metrics)
    repository = SQLiteDurableJobRepository(connection)
    application = DurableJobApplicationService(repository, observability=runtime)
    worker = DurableJobWorkerService(repository, observability=runtime)
    submission = JobSubmission(
        job_id="demo-job-id",
        idempotency_scope="demo-scope",
        idempotency_key="demo-idempotency-key",
        tenant_id="tenant-demo",
        workspace_id="workspace-demo",
        entity_id="entity-demo",
        input_digest="a" * 64,
        config_digest="b" * 64,
        worker_version="worker/1",
        total_units=1,
        retry_ceiling=1,
        created_at="2026-07-27T10:00:00Z",
    )
    application.submit(submission, actor_id="actor-demo")
    claimed = worker.claim(
        tenant_id="tenant-demo",
        worker_id="worker-demo",
        occurred_at="2026-07-27T10:00:01Z",
        lease_expires_at="2026-07-27T10:01:01Z",
    )
    assert claimed is not None
    completed = worker.complete(
        claimed,
        occurred_at="2026-07-27T10:00:02Z",
        output_manifest=JobOutputManifest(1, "c" * 64, "manifest/secret-job"),
    )
    assert completed.status.value == "completed"
    application.submit(
        replace(submission, job_id="demo-fail-job-id", idempotency_key="demo-fail-key"),
        actor_id="actor-demo",
    )
    failed_claim = worker.claim(
        tenant_id="tenant-demo",
        worker_id="worker-demo",
        occurred_at="2026-07-27T10:00:03Z",
        lease_expires_at="2026-07-27T10:01:03Z",
    )
    assert failed_claim is not None
    connection.close()
    with pytest.raises(sqlite3.ProgrammingError):
        worker.fail(failed_claim, occurred_at="2026-07-27T10:00:04Z", safe_error_code="STORAGE_FAILURE")

    serialized = str([(span.name, dict(span.attributes or {})) for span in exporter.get_finished_spans()])
    assert all(name in serialized for name in ("reconforge.job.submit", "reconforge.job.claim", "reconforge.job.complete", "reconforge.job.fail"))
    job_metric = next(
        metric
        for resource in metrics.get_metrics_data().resource_metrics
        for scope in resource.scope_metrics
        for metric in scope.metrics
        if metric.name == "reconforge.jobs.transitions"
    )
    assert any(
        point.attributes.get("reconforge.operation") == "fail"
        and point.attributes.get("reconforge.result") == "error"
        for point in job_metric.data.data_points
    )
    for sensitive_fragment in (
        "demo-job-id",
        "demo-scope",
        "demo-idempotency-key",
        "tenant-demo",
        "workspace-demo",
        "entity-demo",
        "actor-demo",
        "worker-demo",
    ):
        assert sensitive_fragment not in serialized


def test_reliability_measurements_are_closed_dimension_free_metrics() -> None:
    metrics = InMemoryMetricReader()
    runtime = ObservabilityRuntime.create(metric_reader=metrics)
    runtime.record_reliability_measurement(MetricKey.QUEUE_DEPTH, 17)
    exported = metrics.get_metrics_data()
    named = {
        metric.name: metric
        for resource in exported.resource_metrics
        for scope in resource.scope_metrics
        for metric in scope.metrics
    }
    metric = named["reconforge.operations.job_queue_depth"]
    assert metric.data.data_points[0].attributes == {}
    with pytest.raises(ObservabilityConfigurationError, match="measurement is invalid"):
        runtime.record_reliability_measurement(MetricKey.QUEUE_DEPTH, -1)


def test_otlp_configuration_rejects_untrusted_or_plaintext_remote_egress(tmp_path: Path) -> None:
    with pytest.raises(ObservabilityConfigurationError, match="allowlisted"):
        OTLPHTTPConfiguration("https://collector.example:4318")
    with pytest.raises(ObservabilityConfigurationError, match="Plaintext"):
        OTLPHTTPConfiguration("http://collector.example:4318", allowed_hosts=("collector.example",))
    with pytest.raises(ObservabilityConfigurationError, match="no path"):
        OTLPHTTPConfiguration("https://collector.example:4318/v1", allowed_hosts=("collector.example",))
    with pytest.raises(ObservabilityConfigurationError, match="does not exist"):
        OTLPHTTPConfiguration("http://127.0.0.1:4318", certificate_file=tmp_path / "missing.pem")


def test_otlp_http_exports_safe_trace_and_metrics_to_explicit_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    received: list[tuple[str, bytes]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            size = int(self.headers.get("content-length", "0"))
            received.append((self.path, self.rfile.read(size)))
            self.send_response(200)
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
    runtime = create_otlp_http_runtime(
        OTLPHTTPConfiguration(f"http://127.0.0.1:{server.server_port}", export_interval_millis=300_000)
    )
    try:
        with runtime.span("reconforge.otlp.drill", {"reconforge.operation": "collector-drill"}):
            runtime.record_reliability_measurement(MetricKey.QUEUE_DEPTH, 3)
            runtime.record_event("dependency.recovered", {"reconforge.result": "normal"})
        assert runtime.force_flush()
    finally:
        runtime.shutdown()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    paths = {path for path, _ in received}
    assert {"/v1/traces", "/v1/metrics", "/v1/logs"} <= paths
    serialized = b"".join(body for _, body in received)
    assert b"collector-drill" in serialized
    assert b"tenant_id" not in serialized and b"amount" not in serialized


def test_operational_log_events_reject_arbitrary_messages() -> None:
    runtime = ObservabilityRuntime.create()
    try:
        with pytest.raises(ObservabilityConfigurationError, match="event name"):
            runtime.record_event("raw customer row: 100 USD", {})
    finally:
        runtime.shutdown()
