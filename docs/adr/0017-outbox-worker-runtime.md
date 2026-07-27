# ADR 0017: Bounded Transactional-Outbox Worker Runtime

- Status: Accepted as a foundation; managed transport integration pending
- Date: 2026-07-23
- Decision owners: ReconForge maintainers

## Context

The local transactional outbox already has claim leases, retry/backoff,
dead-letter, and replay semantics, but the API process should not be the only
possible place to invoke delivery. A worker boundary is needed without
pretending that an injected publisher is a production queue or transport.

## Decision

Add `OutboxWorker` with an explicit connection factory, publisher, and validated
settings. Each polling cycle opens one fresh database connection, constructs an
`OutboxService`, processes a bounded batch, and closes the connection in a
`finally` block. The worker supports a `threading.Event` stop signal and an
optional bounded cycle count for smoke tests and controlled jobs.

Publisher failures remain in the outbox retry/dead-letter state machine. Worker
configuration and cycle errors are wrapped in a safe `OutboxWorkerError` while
preserving the original cause for logs handled by the deployment layer.

## Consequences

- Connection and transaction state do not leak between polling cycles.
- Multiple workers can rely on the existing outbox lease claim semantics, subject
  to the database backend's locking guarantees.
- External queues, transport authentication, tenant context, metrics, and
  process supervision remain deployment responsibilities.
- A publisher must be idempotent because a lease can expire after delivery and
  before the durable published marker is committed.

## Rejected alternatives

- A global long-lived SQLite connection: unsafe across lifecycle boundaries and
  makes failures persist into later cycles.
- A built-in HTTP publisher with undocumented credentials: would create an
  insecure, misleading transport claim.
- Silent worker retries outside the outbox state machine: would make attempts
  and dead-letter evidence non-reproducible.
