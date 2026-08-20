# ADR 0495: Verify persistent scheduler coordination across processes

- **Status**: Accepted
- **Date**: 2026-08-10
- **Context**: The durable-job scheduler already persisted a tenant-scoped,
  lane-digest-bound cursor, but the PostgreSQL runtime gate exercised only a
  process-local round-robin scheduler. That left the shared cursor's lock and
  update behavior across scheduler instances unproven.
- **Decision**: Add a small server-boundaries contract that seeds one job per
  lane, starts two spawned worker processes, and has each process create its
  own PostgreSQL connection and `PersistentRoundRobinDurableJobScheduler`.
  Each process must claim one exact workspace/entity lane and cancel it through
  the normal lease-fenced worker path. The cursor and leases are inspected by
  the parent under tenant scope after both processes exit.
- **Verification**: Three local repetitions against PostgreSQL 16 returned one
  claim for each lane, advanced the shared cursor to `(next_index=1,
  version=3)`, and left zero leases. The server-boundaries workflow and its
  contract test invoke the gate.
- **Boundary**: This is synthetic two-process, one-host correctness evidence.
  It does not prove cross-host fairness, queue HA/failover, throughput, soak,
  capacity, RPO/RTO, or production scheduling SLOs.
- **Rollback**: Remove the additive test, workflow selector, and evidence
  records; no product data or schema is changed.
