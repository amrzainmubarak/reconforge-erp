# ADR 0496: Verify PostgreSQL worker recovery after a committed checkpoint

- **Status**: Accepted
- **Date**: 2026-08-10
- **Context**: Durable jobs already persisted checkpoints and lease generations,
  but the live PostgreSQL gate only covered an orderly reconnect. A process
  crash after a checkpoint could still lose the lease or duplicate the committed
  business effect if takeover semantics were wrong.
- **Decision**: Add a server-boundaries contract that starts a real spawned
  worker process, claims a two-partition job, commits the first partition, and
  exits without releasing its lease or closing the connection. A fresh process
  must reclaim the expired lease with generation 2, observe the first effect,
  complete the second partition exactly once, and leave ordered lease evidence.
  Logical timestamps are used so the test does not sleep or depend on wall-clock
  timing.
- **Verification**: Three local repetitions against PostgreSQL 16 pass with
  effects `crash/p1` and `crash/p2` exactly once and lease actions
  `claimed/taken_over/released`.
- **Boundary**: Synthetic one-host PostgreSQL crash/resume evidence only. It
  does not prove queue HA, cross-host recovery, capacity, soak, RPO/RTO, or
  production SLOs.
- **Rollback**: Remove the additive test, workflow selector, and evidence
  records; no product schema or user data is changed.
