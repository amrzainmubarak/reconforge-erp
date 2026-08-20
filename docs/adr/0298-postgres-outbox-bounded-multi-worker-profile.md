# ADR 0298: PostgreSQL outbox bounded multi-worker delivery profile

- Date: 2026-08-03
- Status: accepted

## Decision

Add a bounded runtime profile over the existing PostgreSQL transactional
outbox worker. Four independent workers claim and publish 64 synthetic events
from one tenant-scoped queue in batches of eight. A shared injected sink
records event IDs so duplicate publish attempts are observable rather than
hidden.

The acceptance result requires all 64 events to be published once and the
pending, claimed, and dead queues to be empty. The effect digest and
structural manifest digest are evidence; runtime is an observation only.

## Boundary

The publisher is an in-process synthetic sink on one PostgreSQL 16 service
host. This does not prove broker semantics, crash-after-publish recovery,
cross-host supervision, queue HA, failover, throughput, soak, SLO, or
production delivery.

## Rollback

Remove the benchmark module, focused tests, ADR, and execution records. No
schema migration or external delivery is introduced.
