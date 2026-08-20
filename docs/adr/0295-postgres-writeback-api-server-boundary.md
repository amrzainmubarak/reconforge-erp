# ADR 0295: PostgreSQL write-back intent API server boundary

- Date: 2026-08-03
- Status: accepted

## Decision

When the explicit PostgreSQL server profile is enabled, the existing
`/api/v1/connectors/writeback/intents` proposal, approval, and acknowledgement
routes use `PostgresWritebackIntentRepository` through a request-scoped
tenant/workspace boundary. Local mode continues to use the SQLite adapter.

The server routes bind the proposal actor to the authenticated principal,
require the request tenant/workspace headers to equal the intent scope, and
keep network dispatch disabled. Approval remains maker-checker and
acknowledgement remains idempotency-key bound.

## Evidence

The route contract test proves that an enabled server boundary invokes the
PostgreSQL operation seam and returns an explicit PostgreSQL source marker.
The existing live PostgreSQL repository gate proves the persistence, RLS,
replay, lifecycle, and append-only controls underneath that seam.

## Consequences and limits

This closes API/backend selection and scope binding for durable intent evidence.
It does not prove an authenticated hosted API process against a live provider,
secret-vault integration, network write-back, compensation delivery,
provider-version interoperability, throughput, HA/DR, or production readiness.

## Rollback

Removing the server factory alias or route branch returns server-profile
write-back requests to an explicit unavailable response; SQLite local mode is
unchanged. No provider or external system is mutated by this decision.
