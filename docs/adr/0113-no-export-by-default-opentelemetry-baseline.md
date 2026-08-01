# ADR 0113: No-export-by-default OpenTelemetry baseline

- Status: Accepted
- Date: 2026-07-27

## Context

Request IDs and conventional logs existed, but API and durable-job execution
had no vendor-neutral trace/metric boundary or tested data-minimization policy.
Automatic instrumentation and environment-selected exporters could introduce
unreviewed network egress or high-cardinality financial and tenant data.

Official OpenTelemetry Python documentation reports traces and metrics as
stable and logs as development. OpenTelemetry API/SDK 1.44.0 is the stable
release pinned for this slice:

- https://opentelemetry.io/docs/languages/python/
- https://opentelemetry.io/docs/languages/python/instrumentation/
- https://pypi.org/project/opentelemetry-sdk/1.44.0/

## Decision

Provide an optional `observability` extra pinned to OpenTelemetry API/SDK
1.44.0. The application default is a zero-export runtime: it imports no SDK,
opens no network connection, and records nothing. Enabling telemetry creates
isolated tracer and meter providers; an exporter or metric reader must be
injected explicitly. Environment variables do not silently select an exporter.

Instrument normalized API route templates and durable-job lifecycle operations.
Accept only a closed low-cardinality attribute allowlist with bounded string and
integer values; reject floats and tenant, workspace, entity, actor, record,
amount, currency, path, request-body, and job identifiers. Standard logging
handlers gain request/trace/span correlation fields, while message content
remains under the existing logging policy. Do not adopt the developing
OpenTelemetry logs signal in this baseline.

## Consequences

Operators can attach an approved local/customer-managed exporter without
coupling domain code to a vendor. Tests inspect real in-memory SDK spans and
metrics and prove secret-shaped identifiers are absent. Network export, TLS,
collector authentication, sampling, cardinality budgets, retention, dashboards,
alerts, and production SLO evidence remain deployment gates.
