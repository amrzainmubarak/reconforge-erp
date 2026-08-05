# ADR 0337: Publish a PostgreSQL durable-job 100K-effect tier

- Status: accepted
- Date: 2026-08-05
- Scope: `P4-SCL-001`

## Decision

Publish `postgres-durable-job-load/100k-effects-v1` as a bounded PostgreSQL
correctness/concurrency tier: 16 independent worker connections, 2,500
synthetic jobs, forty partitions per job, and four forced-RLS tenant lanes.
Retain the 10K-effect and 256-effect profiles as hosted compatibility tiers.

The tier reuses the existing durable-job lease, checkpoint, idempotency,
partition-effect uniqueness, and queue-drain contracts. Its result records
per-lane completion counts, duplicate effects, queue/running residue, effect
digest, structural manifest digest, and observational timing.

## Rationale

The live PostgreSQL gate previously stopped at 10,000 effects. A 100,000-effect
profile exercises the same multi-worker and tenant-isolation invariants at a
materially larger workload without turning one-host timing into a capacity
claim. The profile keeps the job count and worker count stable so the increased
effect cardinality is explicit and reproducible.

## Evidence boundary

The artifact is synthetic, one-host, and one PostgreSQL service. It does not
prove soak behavior, backpressure coupling, queue HA, automatic failover,
host loss, cross-host fairness, RPO/RTO, or production sizing. Hosted CI must
run the same declared profile before this slice is promoted as hosted evidence.

## Rollback

Remove the tier factory, live test, artifact/schema, benchmark note, manifest
entries, workflow invocation, and execution records. The existing 10K and
256-effect profiles and durable-job runtime remain unchanged.
