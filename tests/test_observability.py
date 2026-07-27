from __future__ import annotations

import logging
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
    TelemetryCorrelationFilter,
    safe_attributes,
    telemetry_request_context,
)


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
    assert metric_names == {"reconforge.http.server.duration", "reconforge.http.server.requests"}


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
