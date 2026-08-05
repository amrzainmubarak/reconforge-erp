# ADR 0340: Add a PostgreSQL durable-job backpressure runtime gate

- Status: accepted
- Date: 2026-08-05
- Scope: `P4-SCL-001`

## Decision

Add `postgres-durable-job-load/backpressure-tier-v1` as a bounded PostgreSQL
runtime profile. It uses eight independent worker connections, four producer
lanes, 64 synthetic jobs, four partitions per job, and an atomic cap of four
queued/retrying jobs per tenant/workspace/entity lane. Producers retry an
explicit `DurableJobBackpressureError`; workers claim, checkpoint, commit
effects, and release leases through the existing PostgreSQL repository.

The gate records submitted/rejected attempts, observed and final queue depths,
completed jobs, partition-effect cardinality, per-lane completion counts, and
effect/manifest digests. The live test requires a non-privileged PostgreSQL
role and keeps the profile skipped when no test DSN is provided.

## Rationale

SQLite already had a local producer-cap profile, while PostgreSQL had only
load and contention evidence. This slice exercises the same bounded-submit
contract against real forced-RLS PostgreSQL transactions and independent
producer/worker connections, without converting one-host timing into a
capacity promise.

## Evidence boundary

The profile is synthetic, single-host, and bounded. It does not prove global
quota fairness, distributed backpressure, broker semantics, throughput,
capacity, soak, queue HA, automatic failover, host loss, cross-host fairness,
RPO/RTO, or production sizing. It does not activate any provider or network
connector.

## Rollback

Remove the profile module, focused tests, workflow selector, benchmark note,
ADR, manifest entries, and execution records. Existing durable-job repository
behavior, lower PostgreSQL tiers, and SQLite backpressure evidence remain
unchanged.
