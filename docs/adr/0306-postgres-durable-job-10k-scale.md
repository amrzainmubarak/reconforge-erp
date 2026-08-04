# ADR 0306: Publish a PostgreSQL durable-job 10K-effect tier

- Status: accepted
- Date: 2026-08-04
- Scope: `P4-SCL-001`

## Decision

Publish `postgres-durable-job-load/10k-effects-v1` as a bounded PostgreSQL
correctness/concurrency tier: 16 independent worker connections, 2,500
synthetic jobs, four partitions per job, and four forced-RLS tenant lanes.
Retain the existing 256-effect profile as the hosted compatibility baseline.

The tier reuses the existing durable-job lease, checkpoint, idempotency,
partition-effect uniqueness, and queue-drain contracts. Its result records
per-lane completion counts, duplicate effects, queue/running residue, effect
digest, structural manifest digest, and observational timing.

## Rationale

SQLite already publishes 10K and 100K durable-job observations, but the real
PostgreSQL concurrency gate stopped at 256 effects. A 10K PostgreSQL run gives
backend-specific evidence for a material workload while preserving the rule
that one-host observations are not capacity, SLO, or HA/DR claims.

## Evidence boundary

The artifact is synthetic, one-host, and one PostgreSQL service. It does not
prove soak behavior, backpressure coupling, queue HA, automatic failover,
host loss, cross-host fairness, RPO/RTO, or production sizing. The local run
uses fixed stable job IDs for replayable digests; live tests use an isolated
prefix to avoid collisions in a shared CI database.

## Rollback

Remove the tier factory, live test, artifact/schema, benchmark note, manifest
entries, and execution records. The existing 256-effect profile and durable
job runtime remain unchanged.
