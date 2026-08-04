# ADR 0309: Run the PostgreSQL durable-job 10K tier as a hosted gate

- Status: accepted
- Date: 2026-08-04
- Scope: bounded PostgreSQL concurrent durable-job correctness evidence

## Context

ReconForge already had a reproducible local PostgreSQL profile with 16 worker
connections, 2,500 jobs, four partitions per job, four tenant lanes, and
10,000 committed effects. The profile proved zero duplicate effects and a
drained queue, but the evidence was local-only.

## Decision

Extend the existing `server-boundaries` CI command to run
`test_live_postgres_durable_job_10k_multi_worker_scale_profile` against the
digest-pinned PostgreSQL 16 service and the non-privileged application role.
The test reuses the production repository/application worker path and keeps
the declared synthetic tenant lanes and effect checks.

## Evidence boundary

This proves a repeatable hosted single-node PostgreSQL correctness/concurrency
tier: 2,500 completed jobs and 10,000 unique committed effects with no queue
residue. It does not prove throughput capacity, soak, backpressure coupling,
distributed fairness, queue HA, host loss, RPO/RTO, or production sizing.

## Rollback

Remove the explicit 10K test invocation, this ADR, its manifest entry, and the
workflow contract assertion. Existing local profile evidence and the smaller
hosted 256-effect baseline remain unchanged.
