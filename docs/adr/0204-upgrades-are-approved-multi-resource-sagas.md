# ADR 0204: Upgrades are approved multi-resource sagas

- Status: Accepted
- Date: 2026-07-30

## Decision

Represent an upgrade as a closed, digest-addressed plan over application,
database, object-store, configuration, and pack resources. Every adapter must
complete compatibility and rollback preflight before any adapter mutates state.
The plan binds the operator runtime separately from deployed current/target versions, verified release-
manifest digest, exact resource versions, target digests, and named compatibility
readers.

Preparation and approval use distinct actor identities. Execution claims the
approved plan atomically and records evidence in a synchronous SQLite journal.
Resources apply in fixed order and roll back in reverse order. An adapter must
classify interrupted work as provably not applied, applied with a receipt, or
uncertain. Uncertain state is isolated and never reported as successfully rolled
back.

## Consequences

This is a saga, not a distributed transaction or an exactly-once claim. Adapters
must be independently idempotent and verify their own receipts. Supported transitions
are closed in a schema-validated matrix. Tagged offline wheels, Community SQLite,
PostgreSQL encrypted restore/Alembic, immutable local object catalogs, strict configuration,
and signed packs have compatibility and rollback drills; one all-resource local plan proves
the fixed composition order. This remains bounded release engineering, not zero-downtime,
HA/DR, production key custody, or distributed-transaction evidence.

## Rollback

Remove the orchestration entry point while retaining its journal as operational
evidence. Resource-specific rollback remains owned by existing backup, migration,
object, configuration, and pack tools.
