# ADR 0297: PostgreSQL durable-job bounded multi-worker scale profile

- Date: 2026-08-03
- Status: accepted

## Decision

Add a reproducible, provider-neutral PostgreSQL runtime profile around the
existing durable-job repository. The profile submits 64 synthetic jobs across
four tenant lanes, commits four partition effects per job, and drains the
queue with eight worker threads using independent PostgreSQL connections.

The profile verifies structural invariants only: tenant/workspace/entity
scope, generation-fenced leases, `FOR UPDATE SKIP LOCKED` claim ownership,
exactly 256 committed partition effects, zero duplicate effects, completed
terminal states, and zero queued/running rows after the drain. Timing and
throughput are retained as observations and excluded from the manifest digest.

The run also hardens `claim_next` with an in-transaction active-lease
recheck. This prevents a stale join snapshot under contention from turning a
live lease into a takeover; only an explicitly expired lease can be reclaimed.

## Rationale

The existing SQLite 10K/100K profiles and small PostgreSQL contention tests
left a gap between local scale evidence and a real multi-connection
PostgreSQL queue. This slice closes that gap without changing the persistence
schema or implying a capacity number.

## Boundary

The CI service is one synthetic PostgreSQL 16 host. This is not evidence for
throughput, a service-level objective, distributed fairness, queue HA,
automatic failover, host loss, RPO/RTO, soak behavior, or production sizing.
It does not add live ERP/bank connectors or write-back.

## Rollback

Remove the benchmark module, focused profile tests, this ADR, and the
execution evidence. No schema migration or external system state is changed.
