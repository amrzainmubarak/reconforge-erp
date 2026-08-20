# ADR 0245: PostgreSQL durable-job runtime gate is bounded

- **Status:** Accepted
- **Date:** 2026-08-02

## Decision

Promote the existing PostgreSQL durable-job application and worker contracts
only after the CI server-boundary job runs their live test against the pinned
PostgreSQL 16 image and a non-privileged application role. The gate covers
concurrent idempotent submission, cancellation, leases/heartbeats, partition
effects, stale-worker rejection, crash/reconnect resume, and SQLite semantic
parity.

## Boundary

This is a single-node synthetic runtime gate. It does not prove queue-provider
HA, multi-host scheduling, capacity/soak limits, failover, RPO/RTO, or
production sizing.
