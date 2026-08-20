# ADR 0498: Reconnect Redis reads once without replaying mutations

- **Status**: Accepted
- **Date**: 2026-08-10
- **Context**: The Redis adapter reused a client after a transient socket or
  timeout failure. Reusing a dead pool hurts read availability, while blindly
  replaying a failed `INCR`, `SET`, lock script, or revocation can duplicate an
  effect that Redis already applied.
- **Decision**: Classify only Redis connection/timeout failures as reconnectable
  and allow one retry for reads and health checks after closing the stale pool.
  Keep mutating operations fail-closed with no automatic retry. The policy
  cache generation follows the same read-versus-mutation split.
- **Verification**: E-661 proves one reconnect in synthetic failure injection
  and zero reconnects for ambiguous mutations. A real `redis:7-alpine` runtime
  passes the 13-test foundation suite after an explicit connection-pool
  disconnect and successful session read recovery.
- **Boundary**: One-host adapter evidence only. Sentinel/Cluster failover,
  server outage, cross-host durability, distributed quota semantics, RPO/RTO,
  and production SLOs remain unverified.
- **Rollback**: Revert the adapter retry flag, tests, and documentation; no
  schema or application data is changed.
