# ADR 0214: Durable-job cancellation profile is structural and non-claim

## Context

The first P4-SCL-001 slice proved no duplicate effects under concurrent SQLite
workers. Cancellation is the next reversible failure-path slice, but a local
small-tier run must not be presented as backpressure, soak, distributed
capacity, or a published scale benchmark.

## Decision

1. Add a bounded cancellation-under-load harness over the existing durable-job
   application and SQLite repository. Do not add a migration, persistence
   primitive, API, CLI, UI, or external provider.
2. Cancel a declared queued subset before worker claims, then assert that
   cancelled jobs produce no effects while non-cancelled jobs complete exactly
   once and the queue drains.
3. Exercise a separate running-job cancellation path that commits a bounded
   prefix, transitions the owner to `cancelled`, and verifies lease release.
4. Keep structural result digests independent of runtime and peak-memory
   observations. Record the small tier and every unproved capability in the
   manifest limitations.

## Consequences

P4-SCL-001 now has local queued and running cancellation evidence with no
duplicate-effect and lease-release checks. It does not prove backpressure,
retry/backoff coupling, soak, PostgreSQL parity, distributed capacity,
10K/100K/1M/10M tiers, SLOs, or production readiness.

## Rollback

Remove the harness, focused tests, manifest entry, and this ADR. No database
migration, source system, hosted service, release, or production state is
mutated.
