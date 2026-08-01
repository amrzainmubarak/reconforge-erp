# ADR 0130: Live Studio fail-closed read contract

- Status: Accepted
- Date: 2026-07-28

## Context

P2-007 requires the browser to consume authorized operational data and make
loading, no-data, stale, and failure states explicit. Reusing synthetic
showcase data after a live failure would hide authorization or availability
problems and could cause a reviewer to treat a fixture as current evidence.

## Decision

The additive `/live` page reads only the existing same-origin
`/api/v1/metrics/dashboard` endpoint. That API route requires `metrics.read`.
The request uses `credentials: same-origin` and `cache: no-store`; its response
must contain only a metrics envelope, each metric may contain only known API
fields, exact decimal text and timestamps are validated, and presentation order
is deterministic. Freshness is derived from the newest valid timestamp against
a bounded threshold.

The UI independently renders loading, empty, fresh, stale, authentication,
permission, server, malformed-contract, and retry states. The loader contains
no demo URL and performs no fallback request. It exposes no mutation action.

## Consequences

- Permission and service failures remain visible and cannot be mistaken for
  fixture-backed success.
- Exact `value_text` and lineage remain inspectable without binary-float
  conversion.
- Deployed cookie/session configuration, live PostgreSQL operation, signed
  response provenance, uptime, and production readiness require separate
  runtime evidence.
- Rollback removes an additive route, loader, and types; no data migration is
  required.
