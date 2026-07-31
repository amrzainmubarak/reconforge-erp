# ADR 0166: PostgreSQL Outbox Application semantic parity

## Status

Accepted — 2026-07-28

## Context

The tenant-bound PostgreSQL adapter already matched all five repository
signatures, but remained contract-only. Two behavioral gaps were material:
Application `pending` in SQLite includes leased but unpublished events while the
PostgreSQL list excluded `Claimed`, and PostgreSQL Dead state had no transition
timestamp to populate the shared `dead_lettered_at` field.

## Decision

Add migration 0033 with `dead_lettered_at` and a database state/identity guard.
Application `pending` now returns both Pending and Claimed rows, matching the
shared meaning of unpublished and not dead-lettered. Dead transition writes a
real database timestamp; replay clears it. The adapter maps that timestamp
without fabrication.

The guard freezes event type, aggregate identity, payload, and creation time.
It independently requires mutually consistent Pending, Claimed, Published, and
Dead metadata. Existing historical Dead rows are not backfilled with invented
timestamps; they remain readable with null until explicitly replayed or managed
under a separate migration policy. Claims continue to use tenant predicates,
`FOR UPDATE SKIP LOCKED`, bounded leases, deterministic ordering, and explicit
worker ownership. External publication remains at-least-once; event ID is the
consumer idempotency key.

## Consequences

The Application model gains honest dead-letter evidence and cross-backend
pending-list semantics. A complete optional non-superuser lifecycle verifies
disjoint claims, pending visibility, dead-letter timestamp, replay, publish, and
RLS. No exactly-once, broker durability, current-live, or external publisher
claim is made without deployment evidence.
