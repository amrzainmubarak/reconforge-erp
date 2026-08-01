from __future__ import annotations

import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from reconforge.api import create_api_app
from reconforge.application.jobs import DurableJobApplicationService, DurableJobWorkerService, JobSubmission
from reconforge.db import connect, run_migrations
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


def test_opentelemetry_api_trace_and_metrics_are_safe_and_correlated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "observability.db"
    run_migrations(db_path)
    spans = InMemorySpanExporter()
    metrics = InMemoryMetricReader()
    monkeypatch.setenv("OTEL_RESOURCE_ATTRIBUTES", "tenant_id=SECRET-TENANT,amount=100")
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
    runtime = ObservabilityRuntime.create(span_exporter=exporter)
    repository = SQLiteDurableJobRepository(connection)
    application = DurableJobApplicationService(repository, observability=runtime)
    worker = DurableJobWorkerService(repository, observability=runtime)
    submission = JobSubmission(
        job_id="SECRET-JOB-ID",
        idempotency_scope="SECRET-SCOPE",
        idempotency_key="SECRET-KEY",
        tenant_id="SECRET-TENANT",
        workspace_id="SECRET-WORKSPACE",
        entity_id="SECRET-ENTITY",
        input_digest="a" * 64,
        config_digest="b" * 64,
        worker_version="worker/1",
        total_units=1,
        retry_ceiling=1,
        created_at="2026-07-27T10:00:00Z",
    )
    application.submit(submission, actor_id="SECRET-ACTOR")
    claimed = worker.claim(
        tenant_id="SECRET-TENANT",
        worker_id="SECRET-WORKER",
        occurred_at="2026-07-27T10:00:01Z",
        lease_expires_at="2026-07-27T10:01:01Z",
    )
    connection.close()

    assert claimed is not None
    serialized = str([(span.name, dict(span.attributes or {})) for span in exporter.get_finished_spans()])
    assert "reconforge.job.submit" in serialized and "reconforge.job.claim" in serialized
    for secret in ("SECRET-JOB-ID", "SECRET-SCOPE", "SECRET-KEY", "SECRET-TENANT", "SECRET-WORKSPACE", "SECRET-ENTITY", "SECRET-ACTOR", "SECRET-WORKER"):
        assert secret not in serialized


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
