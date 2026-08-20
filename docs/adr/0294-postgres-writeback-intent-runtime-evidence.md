# ADR 0294: PostgreSQL write-back intent runtime evidence

- Date: 2026-08-03
- Status: accepted

## Decision

Add an additive PostgreSQL persistence boundary for the existing governed
write-back intent lifecycle. Migration `0061_pg_writeback_intents` stores only
the canonical intent JSON, its digest, lifecycle version, tenant/workspace
scope, and timestamp. Forced RLS, an append-only trigger, idempotent replay,
optimistic version checks, and explicit status transitions apply inside the
repository transaction. Same-intent writers use a transaction-scoped
PostgreSQL advisory lock, so the application role needs only SELECT and INSERT
on the append-only table.

## Rationale

The local SQLite proposal/approval/acknowledgement lifecycle already rejects
self-approval and provider-key mismatches. PostgreSQL server deployments need
the same durable evidence boundary before a provider adapter can be considered.
The schema deliberately stores no provider payload, credential, or response
secret and performs no network operation.

## Consequences and limits

The live CI gate proves synthetic non-superuser PostgreSQL persistence,
workspace/tenant isolation, idempotent replay, maker-checker lifecycle
versions, optimistic conflict refusal, and append-only mutation refusal. It
does not claim a live ERP/bank connector, provider credential integration,
network write-back, delivery semantics, compensation execution, HA/DR,
throughput, or production readiness.

## Rollback

Migration downgrade refuses while intent evidence exists. An operator must
export and explicitly retire the evidence before removing migration 0061; no
provider or external system is mutated by this slice.
