# ADR 0468: Add a tenant-scoped durable-job queue snapshot

- Status: accepted
- Date: 2026-08-09
- Decision owner: ReconForge execution owner

## Context

Durable jobs already enforce idempotency, leases, checkpoints, retries, and
lane backpressure, but operators could only infer queue health by enumerating
job records. That made queue-depth, running-work, and lease-leak diagnostics
backend-specific and risked exposing identifiers or payload metadata.

## Decision

Add a backend-neutral `DurableJobQueueSnapshot` projection and expose it from
the durable-job application service. SQLite and PostgreSQL compute the same
tenant/lane-scoped counts, queue depth, lease count, and oldest queued/running
timestamps. The projection contains no job IDs, idempotency keys, input or
configuration digests, or financial data. PostgreSQL evaluates it inside the
same tenant RLS transaction used by job reads; SQLite uses fixed-column,
parameterized predicates.

## Boundaries

This is a read-only operational projection and consistency contract. It does
not claim distributed queue HA, host-failure recovery, throughput, capacity,
fairness, SLOs, or production sizing.

## Reversibility

Remove the projection methods, dataclass, focused tests, and documentation;
there is no schema or wire migration.

## Verification

The SQLite durable-job suite passes 13 tests plus declared PostgreSQL/live
profile skips. The PostgreSQL live contract now exercises tenant isolation,
queued/running/retrying counts, and lease visibility when its configured
non-privileged runtime is available.
