# ADR 0229: Publish a bounded 10K durable-job tier without widening the claim

- Date: 2026-08-02
- Status: accepted

## Decision

Publish a reproducible 10K durable-job profile as 1,000 jobs with 10
partition effects each, 16 workers, and four tenant lanes. Reuse the existing
generation-fenced leases, checkpoint commits, idempotency keys, and duplicate
effect verification. Increase the local SQLite busy wait to a bounded 60
seconds so transient `BEGIN IMMEDIATE` contention is retried by SQLite rather
than reported as lost work.

## Evidence boundary

The tier is measured on one Windows 11 host and one shared SQLite database.
It proves only the declared 10,000 committed effects, zero duplicate effects,
queue drain, and reproducible structural/effect digests for that profile. It
does not prove PostgreSQL throughput, backpressure, soak, HA/DR, SLOs, or
100K/1M/10M capacity.

## Rollback

Remove the profile, benchmark report, tests, ADR, and the bounded busy-timeout
change. No schema or external state is changed.
