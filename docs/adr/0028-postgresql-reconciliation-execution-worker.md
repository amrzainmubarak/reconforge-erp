# ADR 0028: Durable PostgreSQL reconciliation execution worker

## Status

Accepted — bounded execution-control capability.

## Context

Persisting reconciliation results is not enough for a hosted deployment. A
worker must be able to claim one run, renew its lease, report progress, stop
cooperatively, retry a failed run, and persist all financial output atomically.
The local matcher currently owns a SQLite transaction and cannot be reused as a
PostgreSQL engine by simply changing its connection.

## Decision

Alembic revision `0010_postgres_reconciliation_execution` adds execution state
to each tenant-scoped reconciliation run:

- queued/running/complete/failed/cancelled status;
- worker ownership, lease expiry, attempt count, progress, and safe error text;
- cooperative cancellation requests and execution timestamps.

`PostgresReconciliationWorker` uses fresh tenant-scoped connections for claim,
matcher execution callbacks, heartbeat, and persistence. The matcher is an
injected contract returning canonical result and exception records. The worker
rejects unsupported output fields, persists results/exceptions through the
repository, and completes only after cardinality invariants pass. Failures are
recorded as retryable state; requeue is explicit and audited. No SQLite matcher
transaction is silently presented as hosted PostgreSQL execution.

## Consequences

Positive:

- Concurrent workers cannot claim an active run twice.
- Expired leases can be reclaimed without deleting partial evidence.
- Cancellation, progress, failure, and retry are visible and auditable.
- The persistence boundary remains independent from matcher implementation.

Remaining work:

- Revision `0011_postgres_reconciliation_checkpoints` provides an append-only
  tenant-scoped checkpoint table. Partition-capable matchers now receive one
  bounded partition at a time from a PostgreSQL server cursor, commit results,
  exceptions, and deterministic output hash atomically, and skip committed
  partitions after an explicit requeue. Global assignment still receives a
  materialized working set, and the in-memory SQLite dependency is schema-only
  and performs no hosted financial writes.
- The bounded authenticated run-submission/input-registration API and the
  multi-worker `PostgresReconciliationScheduler` are implemented. Deployment
  still owns process supervision, tenant enumeration, and service configuration.
- Add live partitioned execution tests against the non-privileged worker role
  and publish 10k/100k/1m benchmark evidence before making scale claims.

## Validation

- Repository execution-state and worker contract tests:
  `tests/test_postgres_reconciliation.py`.
- Migration-chain checks: `tests/test_alembic_postgres.py`.
