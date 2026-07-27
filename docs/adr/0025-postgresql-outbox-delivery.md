# ADR 0025: PostgreSQL Outbox Delivery Boundary

- Status: Accepted as a bounded server slice
- Date: 2026-07-23
- Decision owners: ReconForge maintainers

## Context

The PostgreSQL ledger, master-data, and close-control repositories already
write transactional outbox rows, but delivery was implemented only for local
SQLite. A hosted boundary needs tenant-scoped leases, concurrent-worker
exclusion, retry/dead-letter/replay state, and a worker lifecycle that does not
hold database transactions open while calling an external publisher.

## Decision

Add Alembic revision `0007_postgres_outbox_delivery` with a `claimed_by`
worker-owner column and delivery index. `PostgresOutboxRepository` uses
tenant-scoped `FOR UPDATE SKIP LOCKED` claims, expiring leases, bounded attempt
counts, publisher acknowledgements, exponential retry/backoff, dead-lettering,
explicit replay, deterministic listing, and summary counts. Repository methods
are transaction-neutral; the caller owns commit and rollback.

`PostgresOutboxWorker` opens a fresh tenant-scoped connection for each claim or
state transition. It commits the claim before invoking the publisher, then
acknowledges or releases the lease in a separate transaction. The event ID is
the publisher idempotency key because a crash after an external publish and
before acknowledgement can produce a duplicate delivery.

## Consequences

- PostgreSQL server mutations have a real delivery-state boundary instead of
  merely writing pending rows.
- Multiple workers can claim different tenant events without blocking one
  another, subject to database capacity and tenant enumeration policy.
- External transport, publisher idempotency, crash recovery tests against a
  real service, scheduling, and observability remain deployment concerns.
- Local SQLite outbox behavior remains unchanged.

## Rejected alternatives

- Holding the PostgreSQL transaction open during external publishing: this
  would increase lock duration and cannot make the external side effect
  atomic with the database commit.
- Claiming without `SKIP LOCKED` or worker ownership: concurrent workers could
  publish the same event or acknowledge another worker's lease.
