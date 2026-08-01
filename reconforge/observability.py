"""Optional, no-export-by-default OpenTelemetry traces and metrics."""

from __future__ import annotations

import ipaddress
import logging
import re
from collections.abc import Mapping
from contextlib import AbstractContextManager, contextmanager, nullcontext
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from time import time_ns
from typing import Any
from urllib.parse import urlsplit

from reconforge.reliability import AlertResult, MetricKey

TELEMETRY_POLICY_VERSION = "reconforge-telemetry-attributes-v1"
_SERVICE_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{0,79}$")
_EVENT_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{0,79}$")
_ALLOWED_ATTRIBUTES = frozenset(
    {
        "error.type",
        "http.request.method",
        "http.response.status_code",
        "http.route",
        "job.retry_count",
        "job.status",
        "job.type",
        "reconforge.alert.metric",
        "reconforge.alert.observed",
        "reconforge.alert.policy",
        "reconforge.alert.runbook",
        "reconforge.alert.slo",
        "reconforge.alert.state",
        "reconforge.operation",
        "reconforge.result",
        "reconforge.telemetry.policy",
    }
)
_REQUEST_ID: ContextVar[str] = ContextVar("reconforge_observability_request_id", default="")


class ObservabilityConfigurationError(ValueError):
    """Raised when telemetry configuration could disclose or export unsafe data."""


@dataclass(frozen=True)
class OTLPHTTPConfiguration:
    """Explicit egress configuration; environment-derived endpoints are forbidden."""

    endpoint: str
    allowed_hosts: tuple[str, ...] = ()
    timeout_seconds: int = 10
    export_interval_millis: int = 10_000
    certificate_file: Path | None = None
    client_certificate_file: Path | None = None
    client_key_file: Path | None = None

    def __post_init__(self) -> None:
        parsed = urlsplit(self.endpoint)
        host = (parsed.hostname or "").casefold()
        if parsed.scheme not in {"http", "https"} or not host or parsed.username or parsed.password:
            raise ObservabilityConfigurationError("OTLP endpoint must be an explicit HTTP(S) origin.")
        if parsed.query or parsed.fragment or parsed.path not in {"", "/"} or parsed.port is None:
            raise ObservabilityConfigurationError("OTLP endpoint must include an explicit port and no path/query/fragment.")
        try:
            loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            loopback = host == "localhost"
        allowed = {item.strip().casefold() for item in self.allowed_hosts}
        if not loopback and host not in allowed:
            raise ObservabilityConfigurationError("OTLP host is not explicitly allowlisted.")
        if parsed.scheme == "http" and not loopback:
            raise ObservabilityConfigurationError("Plaintext OTLP is permitted only on loopback.")
        if self.timeout_seconds < 1 or self.timeout_seconds > 60:
            raise ObservabilityConfigurationError("OTLP timeout is outside the supported range.")
        if self.export_interval_millis < 1_000 or self.export_interval_millis > 300_000:
            raise ObservabilityConfigurationError("OTLP metric interval is outside the supported range.")
        if (self.client_certificate_file is None) != (self.client_key_file is None):
            raise ObservabilityConfigurationError("OTLP client certificate and key must be configured together.")
        for file in (self.certificate_file, self.client_certificate_file, self.client_key_file):
            if file is not None and not file.is_file():
                raise ObservabilityConfigurationError("Configured OTLP certificate file does not exist.")


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
        if (
            isinstance(value, bool)
            or isinstance(value, int)
            and not isinstance(value, bool)
            and -(10**12) <= value <= 10**12
            or isinstance(value, str)
            and 0 < len(value) <= 160
            and all(ord(character) >= 32 for character in value)
        ):
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
    reliability_histograms: Mapping[MetricKey, Any] | None = None
    trace_provider: Any = None
    meter_provider: Any = None
    logger_provider: Any = None
    event_logger: Any = None

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
        log_exporter: Any = None,
    ) -> ObservabilityRuntime:
        """Create a local SDK provider without configuring network exporters."""

        if not _SERVICE_PATTERN.fullmatch(service_name):
            raise ObservabilityConfigurationError("Telemetry service name is invalid.")
        try:
            from opentelemetry.sdk._logs import LoggerProvider
            from opentelemetry.sdk._logs.export import SimpleLogRecordProcessor
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
        logger_provider = LoggerProvider(resource=resource)
        if log_exporter is not None:
            logger_provider.add_log_record_processor(SimpleLogRecordProcessor(log_exporter))
        meter = meter_provider.get_meter("reconforge", "1")
        reliability_histograms = {
            key: meter.create_histogram(f"reconforge.operations.{key.value}", unit="1") for key in MetricKey
        }
        return cls(
            enabled=True,
            tracer=trace_provider.get_tracer("reconforge", "1"),
            request_counter=meter.create_counter("reconforge.http.server.requests"),
            request_duration_ms=meter.create_histogram("reconforge.http.server.duration", unit="ms"),
            job_counter=meter.create_counter("reconforge.jobs.transitions"),
            reliability_histograms=reliability_histograms,
            trace_provider=trace_provider,
            meter_provider=meter_provider,
            logger_provider=logger_provider,
            event_logger=logger_provider.get_logger("reconforge", "1"),
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

    def record_reliability_measurement(self, metric: MetricKey, value: int) -> None:
        """Record a closed, dimension-free operational measurement."""

        if not self.enabled:
            return
        if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > 10**12:
            raise ObservabilityConfigurationError("Reliability measurement is invalid.")
        if self.reliability_histograms is None:
            raise ObservabilityConfigurationError("Reliability instruments are unavailable.")
        self.reliability_histograms[metric].record(value)

    def force_flush(self, *, timeout_millis: int = 10_000) -> bool:
        if not self.enabled:
            return True
        return bool(
            self.trace_provider.force_flush(timeout_millis)
            and self.meter_provider.force_flush(timeout_millis)
            and self.logger_provider.force_flush(timeout_millis)
        )

    def shutdown(self, *, timeout_millis: int = 10_000) -> None:
        if self.enabled:
            self.trace_provider.shutdown()
            self.meter_provider.shutdown(timeout_millis)
            self.logger_provider.shutdown()

    def record_event(self, event: str, attributes: Mapping[str, object]) -> None:
        """Emit a schema-closed operational log event, never an arbitrary message."""

        if not self.enabled:
            return
        if not _EVENT_PATTERN.fullmatch(event):
            raise ObservabilityConfigurationError("Telemetry event name is invalid.")
        resolved = safe_attributes({**attributes, "reconforge.telemetry.policy": TELEMETRY_POLICY_VERSION})
        self.event_logger.emit(
            timestamp=time_ns(), severity_text="INFO", body=event, event_name=event, attributes=resolved
        )

    def record_alert(self, result: AlertResult) -> None:
        """Emit one closed alert evaluation for an operator-owned downstream rule."""

        attributes: dict[str, object] = {
            "reconforge.alert.policy": result.policy_id,
            "reconforge.alert.metric": result.metric.value,
            "reconforge.alert.state": result.state.value,
            "reconforge.alert.slo": result.slo_id,
            "reconforge.alert.runbook": result.runbook,
        }
        if result.observed is not None:
            attributes["reconforge.alert.observed"] = result.observed
        self.record_event("reliability.alert", attributes)


def create_otlp_http_runtime(configuration: OTLPHTTPConfiguration) -> ObservabilityRuntime:
    """Create an explicit OTLP/HTTP runtime without environment proxy or endpoint discovery."""

    try:
        import requests
        from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    except ImportError as exc:
        raise ObservabilityConfigurationError(
            "Install ReconForge with the observability extra to enable OTLP/HTTP export."
        ) from exc
    base = configuration.endpoint.rstrip("/")
    certificate_file = str(configuration.certificate_file) if configuration.certificate_file else None
    client_certificate_file = (
        str(configuration.client_certificate_file) if configuration.client_certificate_file else None
    )
    client_key_file = str(configuration.client_key_file) if configuration.client_key_file else None
    trace_session = requests.Session()
    trace_session.trust_env = False
    metric_session = requests.Session()
    metric_session.trust_env = False
    log_session = requests.Session()
    log_session.trust_env = False
    span_exporter = OTLPSpanExporter(
        endpoint=base + "/v1/traces",
        certificate_file=certificate_file,
        client_certificate_file=client_certificate_file,
        client_key_file=client_key_file,
        timeout=configuration.timeout_seconds,
        session=trace_session,
    )
    metric_exporter = OTLPMetricExporter(
        endpoint=base + "/v1/metrics",
        certificate_file=certificate_file,
        client_certificate_file=client_certificate_file,
        client_key_file=client_key_file,
        timeout=configuration.timeout_seconds,
        session=metric_session,
    )
    log_exporter = OTLPLogExporter(
        endpoint=base + "/v1/logs",
        certificate_file=certificate_file,
        client_certificate_file=client_certificate_file,
        client_key_file=client_key_file,
        timeout=configuration.timeout_seconds,
        session=log_session,
    )
    reader = PeriodicExportingMetricReader(
        metric_exporter, export_interval_millis=configuration.export_interval_millis
    )
    return ObservabilityRuntime.create(
        span_exporter=span_exporter, metric_reader=reader, log_exporter=log_exporter
    )
