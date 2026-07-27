"""Optional, no-export-by-default OpenTelemetry traces and metrics."""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from contextlib import AbstractContextManager, contextmanager, nullcontext
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

TELEMETRY_POLICY_VERSION = "reconforge-telemetry-attributes-v1"
_SERVICE_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{0,79}$")
_ALLOWED_ATTRIBUTES = frozenset(
    {
        "error.type",
        "http.request.method",
        "http.response.status_code",
        "http.route",
        "job.retry_count",
        "job.status",
        "job.type",
        "reconforge.operation",
        "reconforge.result",
        "reconforge.telemetry.policy",
    }
)
_REQUEST_ID: ContextVar[str] = ContextVar("reconforge_observability_request_id", default="")


class ObservabilityConfigurationError(ValueError):
    """Raised when telemetry configuration could disclose or export unsafe data."""


@contextmanager
def telemetry_request_context(request_id: str) -> Any:
    """Bind a bounded correlation ID for logs produced during one request."""

    normalized = request_id if 0 < len(request_id) <= 128 and request_id.isascii() and request_id.isprintable() else ""
    token = _REQUEST_ID.set(normalized)
    try:
        yield
    finally:
        _REQUEST_ID.reset(token)


class TelemetryCorrelationFilter(logging.Filter):
    """Attach safe request/trace correlation fields to standard log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        trace_id = ""
        span_id = ""
        try:
            from opentelemetry import trace

            context = trace.get_current_span().get_span_context()
            if context.is_valid:
                trace_id = f"{context.trace_id:032x}"
                span_id = f"{context.span_id:016x}"
        except ImportError:
            pass
        record.reconforge_request_id = _REQUEST_ID.get()
        record.reconforge_trace_id = trace_id
        record.reconforge_span_id = span_id
        record.reconforge_telemetry_policy = TELEMETRY_POLICY_VERSION
        return True


def safe_attributes(values: Mapping[str, object]) -> dict[str, str | int | bool]:
    """Validate a closed low-cardinality attribute contract."""

    if not set(values) <= _ALLOWED_ATTRIBUTES:
        raise ObservabilityConfigurationError("Telemetry attribute is not allowlisted.")
    result: dict[str, str | int | bool] = {}
    for key, value in values.items():
        if isinstance(value, bool) or isinstance(value, int) and not isinstance(value, bool) and -(10**12) <= value <= 10**12 or isinstance(value, str) and 0 < len(value) <= 160 and all(ord(character) >= 32 for character in value):
            result[key] = value
        else:
            raise ObservabilityConfigurationError("Telemetry attribute value is invalid.")
    return result


@dataclass(frozen=True)
class ObservabilityRuntime:
    """Isolated OpenTelemetry runtime; exporters are injected explicitly."""

    enabled: bool
    tracer: Any = None
    request_counter: Any = None
    request_duration_ms: Any = None
    job_counter: Any = None

    @classmethod
    def disabled(cls) -> ObservabilityRuntime:
        return cls(enabled=False)

    @classmethod
    def create(
        cls,
        *,
        service_name: str = "reconforge-api",
        span_exporter: Any = None,
        metric_reader: Any = None,
    ) -> ObservabilityRuntime:
        """Create a local SDK provider without configuring network exporters."""

        if not _SERVICE_PATTERN.fullmatch(service_name):
            raise ObservabilityConfigurationError("Telemetry service name is invalid.")
        try:
            from opentelemetry.sdk.metrics import MeterProvider
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import SimpleSpanProcessor
        except ImportError as exc:
            raise ObservabilityConfigurationError(
                "Install ReconForge with the observability extra to enable OpenTelemetry."
            ) from exc
        # Construct directly: Resource.create() runs environment detectors and
        # would permit unreviewed OTEL_RESOURCE_ATTRIBUTES in this boundary.
        resource = Resource({"service.name": service_name})
        trace_provider = TracerProvider(resource=resource)
        if span_exporter is not None:
            trace_provider.add_span_processor(SimpleSpanProcessor(span_exporter))
        readers = () if metric_reader is None else (metric_reader,)
        meter_provider = MeterProvider(metric_readers=readers, resource=resource)
        meter = meter_provider.get_meter("reconforge", "1")
        return cls(
            enabled=True,
            tracer=trace_provider.get_tracer("reconforge", "1"),
            request_counter=meter.create_counter("reconforge.http.server.requests"),
            request_duration_ms=meter.create_histogram("reconforge.http.server.duration", unit="ms"),
            job_counter=meter.create_counter("reconforge.jobs.transitions"),
        )

    def span(self, name: str, attributes: Mapping[str, object]) -> AbstractContextManager[Any]:
        if not self.enabled:
            return nullcontext(None)
        if not name or len(name) > 120:
            raise ObservabilityConfigurationError("Telemetry span name is invalid.")
        resolved = safe_attributes({**attributes, "reconforge.telemetry.policy": TELEMETRY_POLICY_VERSION})
        return self.tracer.start_as_current_span(name, attributes=resolved)

    def record_request(self, *, duration_ms: int, attributes: Mapping[str, object]) -> None:
        if not self.enabled:
            return
        resolved = safe_attributes({**attributes, "reconforge.telemetry.policy": TELEMETRY_POLICY_VERSION})
        self.request_counter.add(1, resolved)
        self.request_duration_ms.record(duration_ms, resolved)

    def record_job(self, attributes: Mapping[str, object]) -> None:
        if self.enabled:
            resolved = safe_attributes({**attributes, "reconforge.telemetry.policy": TELEMETRY_POLICY_VERSION})
            self.job_counter.add(1, resolved)
