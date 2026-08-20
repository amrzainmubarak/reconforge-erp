# ADR 0530: Gate declaration-only 1M/10M PostgreSQL durable-job scale tiers

- **Date**: 2026-08-12
- **Status**: Accepted
- **Scope**: `P4-SCL-001`

## Context

PostgreSQL durable-job scale has published deterministic evidence for 10K and 100K
committed partition effects in local runtime gates. The next 1M and 10M tier
profiles were needed for roadmap planning, but executing them in default CI runs risks
wall-clock and resource overruns, reducing reliability of baseline release gates.

## Decision

Declare `postgres-durable-job-load/1m-effects-v1` and
`postgres-durable-job-load/10m-effects-v1` profiles in code and schema as
replayable, deterministic declarations only:

- Add factories and structural profile tests in
  `reconforge/benchmark/postgres_durable_job_scale.py` and
  `tests/test_postgres_durable_job_scale.py`.
- Extend the PostgreSQL scale schema to admit the profile IDs and partition-effect
  cardinalities.
- Add live tests guarded by `RECONFORGE_RUN_EXTENDED_POSTGRES_SCALE` in
  `tests/test_postgres_durable_jobs.py` so 1M/10M execution is explicit,
  operator-selected, and out of the default CI gate.

The default CI and baseline gates therefore remain focused on established 10K/100K
and bounded governance runtime contracts while still documenting reproducible
1M/10M declarations.

## Evidence boundary

This ADR records declaration and local test coverage only. `1m-effects-v1` and
`10m-effects-v1` are not executed by default and do not constitute performance,
soak, HA/DR, or production sizing claims.

## Rollback

Remove the two new profile factories, schema enum entries, and gated live tests.
