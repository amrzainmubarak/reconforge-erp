# ADR 0292: Atomic bounded durable-job submission

- **Date:** 2026-08-03
- **Status:** Accepted

## Context

The durable-job worker already has bounded SQLite load and a small live
PostgreSQL claim-contention gate, but producer backpressure was only an
external polling convention. Two producers could therefore observe the same
free capacity and both submit, and idempotent retries had no explicit contract
when the queue was full.

## Decision

Add an additive `submit_bounded` application operation and matching repository
contract. `max_queued_jobs` is enforced atomically for the
`(tenant_id, workspace_id, entity_id)` execution lane and counts both `queued`
and `retrying` jobs. An existing identical idempotency submission is resolved
before the cap and always replays; a new submission at or above the cap raises
`DurableJobBackpressureError` without inserting a row or transition.

SQLite uses `BEGIN IMMEDIATE` for the count-and-insert transaction. PostgreSQL
uses a transaction-scoped advisory lock derived only from the lane identity,
then performs the same scoped count and insert under forced tenant RLS. The
cap is a safety/backpressure primitive, not a throughput, fairness-SLO, or
capacity claim.

## Consequences

- Existing unbounded `submit` callers remain backward compatible.
- Governed callers receive the same central policy and SoD checks through an
  additive bounded method.
- A running or terminal job no longer consumes queued capacity; retrying work
  remains counted until it is claimed or terminally resolved.
- PostgreSQL advisory-lock contention is intentionally scoped to one lane and
  has no external network or queue dependency.

## Verification and limits

The SQLite contract proves atomic rejection, idempotent replay while full,
lane isolation, and capacity release after a claim/cancel transition. The
PostgreSQL server-boundaries test exercises the same semantics under the
non-privileged RLS role. This does not prove distributed quota coordination,
global fairness, backoff tuning, soak behavior, throughput, HA/DR, or
production capacity.

Rollback is additive: stop using `submit_bounded` and continue using the
existing `submit`; no migration or persisted-schema change is required.
