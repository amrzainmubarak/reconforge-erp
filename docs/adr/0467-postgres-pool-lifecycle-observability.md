# ADR 0467: Expose bounded PostgreSQL pool lifecycle evidence

- Status: accepted
- Date: 2026-08-09
- Decision owner: ReconForge execution owner

## Context

The PostgreSQL grouped-worker scale harness uses a bounded connection pool to
avoid unbounded TCP connection churn. The pool enforced a maximum and timeout,
but its lifecycle state was not observable without inspecting private state.
That made leak, idle-release, and shutdown verification less explicit for
load and operational diagnostics.

## Decision

Add a dependency-free `PostgresConnectionPoolSnapshot` containing only
`max_size`, `total`, `idle`, `leased`, and `closed` counters. The snapshot is
thread-safe, contains no DSN, tenant, or financial data, and is exposed by the
pooled factory as `pool_snapshot`. Add a repeated 128-lease, 16-worker
synthetic lifecycle contract that proves the physical connection count never
exceeds the configured four-connection bound, every lease returns through
rollback-on-release, shutdown closes idle connections, and post-close leases
fail closed.

## Boundaries

This is resource-lifecycle and observability evidence for one process. It does
not claim throughput, distributed fairness, queue HA, host failure recovery,
PostgreSQL capacity, or production SLOs.

## Reversibility

Remove the snapshot property and focused contract; no schema, data, or wire
compatibility changes are involved.

## Verification

`tests/test_postgres_foundation.py` passes 13 tests plus one declared live
PostgreSQL skip. Ruff and Mypy pass for the changed runtime and test surface.
