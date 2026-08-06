# ADR 0410: PostgreSQL outbox consumer hierarchy receipts

- **Date**: 2026-08-06
- **Status**: Accepted

## Context

Publisher events now carry workspace, organization, and legal-entity
attribution, but the exactly-once consumer receipt table remained tenant-only.
That allowed a tenant-wide consumer transaction to recognize or write a
receipt without proving the event belonged to the requested business lane.

## Decision

Migration `0074_pg_outbox_consumer_scope` adds nullable hierarchy columns,
transaction-local defaults, a scope-aware receipt index, and explicit RLS to
`outbox_consumer_receipts`. The consumer accepts optional hierarchy scope,
restores it through `PostgresTenantBoundary`, reads the event attribution, and
fails closed on a mismatch before invoking the effect. Receipt inserts retain
the same attribution, while tenant-only legacy events remain compatible.

Downgrade refuses to discard any receipt rows before removing the additive
scope columns, preventing silent loss of exactly-once provenance.

## Verification and boundary

Static schema/migration tests cover forced RLS, indexes, defaults, downgrade
protection, and hierarchy validation. The existing disposable PostgreSQL
consumer drill remains capability-gated in environments without a service.
This proves a bounded database idempotency boundary, not external broker
exactly-once delivery, provider acknowledgement, throughput, HA/DR, or
production readiness.

## Reversibility

With an empty receipt table, downgrade restores the tenant-only policy and
removes only the additive columns/index. Existing tenant-only consumer APIs
remain source-compatible.
