# ADR 0427: Reuse reconciliation scheduler workers

- **Date**: 2026-08-07
- **Status**: accepted

## Context

`PostgresReconciliationScheduler` created a new worker object for every worker
slot on every poll cycle. A worker may own a bounded connection pool or other
lifecycle-scoped resources, so this pattern adds avoidable object and resource
churn during long-running polling.

## Decision

Cache one injected worker instance per validated, stable `worker_id` inside the
scheduler. The factory is called lazily on the first cycle for each slot, and
the scheduler continues to execute one bounded `process_once` call per slot.
Resource cleanup remains owned by the injected worker/factory lifecycle; this
change does not invent a scheduler-level close contract.

## Verification and boundary

The scheduler contract proves that a second cycle reuses both worker instances
and preserves the aggregate summary. Ruff, Mypy, package build, diff-check, and
the full local regression are required for the slice. This is resource-reuse
correctness only; it does not prove throughput, fairness, capacity, soak,
distributed scheduling, HA/DR, or production sizing.
