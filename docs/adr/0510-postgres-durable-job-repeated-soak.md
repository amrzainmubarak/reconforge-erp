# ADR 0510: Bounded repeated PostgreSQL durable-job soak

- **Status:** Accepted
- **Date:** 2026-08-10
- **Decision owners:** ReconForge maintainers

## Context

ReconForge had single-run PostgreSQL scale and queue-cap correctness evidence,
plus a repeated SQLite soak. The remaining narrow gap was repeatability of the
real PostgreSQL worker/repository path without implying distributed capacity.

## Decision

Add `reconforge.benchmark.postgres_durable_job_soak` as a schema-v1 profile
that reuses the existing PostgreSQL multi-worker scale harness. Each bounded
iteration gets unique synthetic tenant lanes in one disposable database, while
the job-ID prefix and profile shape remain stable. The verifier fails closed
unless every declared job/effect completes, queues and running counts drain,
duplicates are zero, and all iteration effect-set digests are equal.

Runtime and machine metadata remain observations outside structural claims.
The profile is bounded to 2–16 iterations and the existing PostgreSQL scale
profile limits. No migration, production connector, or new persistence
primitive is introduced.

## Evidence

`tests/test_postgres_durable_job_soak.py` covers bounds, input isolation,
digest-drift rejection, packaging, and CI selection. The live PostgreSQL gate
is `test_live_postgres_durable_job_soak_profile` in
`tests/test_postgres_durable_jobs.py`. The local report is
`docs/execution/benchmarks/postgres-durable-job-soak-current-2026-08-10.json`.

## Boundary and rollback

This closes only bounded one-host PostgreSQL repetition. Distributed soak,
queue HA, host loss, automatic failover, cross-host fairness, capacity,
throughput, RPO/RTO, and production workload evidence remain open. Roll back by
removing the module, tests, ADR, report, and manifest entries; no persisted-data
migration is involved.
