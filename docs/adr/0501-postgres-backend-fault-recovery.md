# ADR 0501: Gate checkpoint recovery after PostgreSQL backend termination

- **Status**: Accepted
- **Date**: 2026-08-10
- **Decision**: Require a spawned PostgreSQL worker test that commits one
  partition checkpoint, exposes its backend PID only through a bounded temporary
  marker, and is terminated by an independent administration connection.
  Recovery must reclaim the expired lease at generation 2 and complete the
  remaining partition exactly once.
- **Rationale**: A worker-process crash test does not exercise a database/session
  fault. Killing the exact backend after commit proves the durable checkpoint
  and lease fencing survive loss of the worker's PostgreSQL session.
- **Verification**: E-664 passes three local PostgreSQL 16.14 repetitions;
  the server-boundaries workflow and phase contract select the test.
- **Boundary**: One-host synthetic PostgreSQL session failure only. No host/site
  independence, automatic failover, queue HA, cross-host recovery, RPO/RTO,
  throughput, or production scheduling claim follows.
- **Rollback**: Remove the helper, test, workflow selector, ADR, and E-664
  evidence; retain the existing process-crash checkpoint gate.
