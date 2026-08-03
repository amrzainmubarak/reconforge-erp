# ADR 0299: PostgreSQL outbox idempotent-consumer receipt boundary

- Date: 2026-08-03
- Status: accepted

## Decision

Add `outbox_consumer_receipts` as an immutable, tenant-scoped PostgreSQL
receipt table and expose `PostgresOutboxConsumer.apply`. The consumer takes an
event digest and executes a database-local effect callback inside the same
transaction that inserts the receipt. An advisory transaction lock serializes
the same `(tenant, consumer, event)` key. A replay with the same digest returns
`duplicate` without invoking the callback; a changed digest fails closed.

This is the concrete exactly-once business-effect boundary for effects that
are committed in the same PostgreSQL transaction. The callback must not claim
atomicity for an external HTTP/broker/provider side effect; external systems
still require their own idempotency and acknowledgement contract.

## Evidence

The live PostgreSQL contract inserts one outbox event, applies a synthetic
business effect, simulates a process failure before outbox acknowledgement,
reclaims the expired lease, and delivers the event again. The effect count and
receipt count remain one, the second delivery is `duplicate`, the event is
acknowledged, and a different event digest is rejected.

## Security and rollback

The receipt table uses forced RLS, tenant-local transaction scope, an append-
only trigger, SHA-256 digest checks, and stores no event payload or effect
result. Migration `0062_pg_outbox_consumer` refuses downgrade when receipts
exist, preserving evidence. Removing the slice requires an explicit evidence
retention decision and an empty table.

## Boundary

This is one-node PostgreSQL transactional evidence with a synthetic local
effect. It does not prove external broker exactly-once delivery, cross-region
failover, queue HA, throughput, soak, compensation, or production readiness.
