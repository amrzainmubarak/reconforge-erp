# ADR 0384: Repeated durable-job soak stays bounded and structural

- **Status**: Accepted
- **Date**: 2026-08-06
- **Decision owners**: ReconForge maintainers

## Context

ReconForge already had bounded durable-job load, cancellation, retry,
backpressure, and PostgreSQL correctness profiles. A single run does not expose
whether a repeated workload preserves deterministic effects and drains all
queue state. The missing evidence must not be confused with production capacity
or a distributed soak test.

## Decision

Add `reconforge.benchmark.durable_job_soak` with a closed, schema-v1
`DurableJobSoakProfile`. It reuses the public durable-job load harness and runs
each iteration against a fresh SQLite database. The verifier fails closed unless
all declared jobs and partition effects complete, every iteration has the same
effect digest, duplicate effects are zero, and queued/running residue is zero.
Runtime and peak memory are retained as environment observations and excluded
from structural acceptance.

The profile is deliberately bounded to 2-32 iterations and the declared load
profile's existing limits. It introduces no migration, persistence primitive,
network dependency, provider connector, or production sizing claim.

## Evidence

`tests/test_durable_job_soak.py` covers profile bounds, repeated load, manifest
replayability, deterministic aggregate digests, queue drain, and source
distribution membership. The focused soak/load suite is the required local
verification command.

## Boundary and rollback

This is one-host SQLite repetition only. PostgreSQL/distributed soak, queue HA,
host-loss recovery, cross-host fairness, capacity, throughput, SLO/RPO/RTO, and
production readiness remain open. Roll back by removing the module, tests, ADR,
manifest entry, and execution evidence; no persisted-data migration is involved.
