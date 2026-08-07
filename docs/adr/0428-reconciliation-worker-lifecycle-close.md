# ADR 0428: Explicit reconciliation worker lifecycle close

- **Date**: 2026-08-07
- **Status**: accepted

## Context

ADR 0427 keeps one reconciliation worker per stable scheduler slot. A cached
worker can own a connection pool or another managed resource, so a long-lived
process needs an explicit, repeatable shutdown hook.

## Decision

`PostgresReconciliationScheduler.close()` marks the scheduler closed, detaches
cached workers, and invokes each worker's optional `close()` hook once. The
operation is idempotent and reports a safe scheduler error after attempting all
worker hooks. `PostgresReconciliationWorker.close()` delegates once to an
optional connection-factory close hook. The caller must stop the scheduler's
polling loop before calling `close()`; no concurrent-cycle coordination is
invented by this boundary.

## Verification and boundary

Focused contracts prove one-time worker/factory cleanup, closed-scheduler
rejection, and repeated-close idempotency. Ruff, Mypy, package build,
diff-check, and the full local regression are required. This is lifecycle
correctness only; it does not prove connection-provider availability,
throughput, fairness, capacity, soak, distributed scheduling, HA/DR, or
production operations.
