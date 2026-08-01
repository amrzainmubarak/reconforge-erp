# ADR 0208: OTLP export is explicit, allowlisted, and environment-independent

- Status: Accepted
- Date: 2026-07-30

## Context

ADR 0113 established optional no-export-by-default OpenTelemetry. P3-ENT-012
requires exercised collector delivery without allowing environment variables,
proxy discovery, or arbitrary endpoints to silently create egress.

Official OpenTelemetry guidance recommends OTLP and a Collector for production
export, with HTTP/protobuf and gRPC as supported transports:

- https://opentelemetry.io/docs/languages/python/exporters/
- https://opentelemetry.io/docs/specs/otel/protocol/exporter/
- https://github.com/open-telemetry/opentelemetry-collector-releases/releases/tag/v0.153.0

## Decision

Pin the official OTLP HTTP/protobuf exporter to the same 1.44.0 SDK version.
Export remains disabled unless the operator supplies `--otlp-http-endpoint`.
The endpoint must be a path-free origin with an explicit port. Plain HTTP is
loopback-only; every non-loopback HTTPS host needs an exact allowlist entry.
Optional CA and paired mTLS files must exist. Export sessions set
`trust_env=False`, accept no runtime headers, and therefore ignore ambient proxy,
endpoint, and credential variables. The API owns flush/shutdown lifecycle.

## Consequences

Traces, metrics, and schema-closed operational events can reach a vendor-neutral OTLP receiver through a bounded
operator decision. Default local/community operation still creates no exporter
or egress. Header-based collector authentication and arbitrary application-log
export are not supported; standard logs retain safe request/trace correlation,
while OTLP log records accept only validated event codes and allowlisted attributes.
The loopback receiver drill is protocol-delivery evidence, not a full Collector
distribution, backend, alert manager, production SLO, or HA result.

E-226 separately pins and exercises the official Collector Contrib 0.153.0 image
with the repository's closed three-pipeline configuration and an ephemeral file
backend. That closes the local distribution/backend drill only; durable retention,
alert-manager acknowledgement, and HA remain open.

## Rollback

Omit the CLI endpoint to return to the prior disabled runtime. Remove the OTLP
exporter dependency and factory only after downgrading E-223 evidence; API and
local reliability behavior remain otherwise compatible.
