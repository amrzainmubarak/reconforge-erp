# ADR 0134: PostgreSQL journal contract parity

- Status: Accepted
- Date: 2026-07-28

## Context

The journal application port is backend-neutral, but only SQLite implemented
it. Copying its seven financial-control policies into a PostgreSQL adapter
would create two decision authorities. Persisting journal exceptions, the
unified queue, audit evidence, and outbox messages independently could also
leave a partially visible financial-control result.

## Decision

Extract the deterministic journal policy evaluator into the domain layer and
use it from both adapters. Thresholds and stored amounts reject binary floats
and use exact Decimal text. Migration 0016 adds tenant-keyed journal entries,
journal exceptions, and reusable control exceptions. All tables force RLS on
`app.tenant_id`; workspace foreign keys include tenant identity.

The PostgreSQL adapter is constructed with one validated tenant. Import and
policy operations set transaction-local scope and atomically write the primary
records, shared control queue, existing domain audit hash chain, and existing
transactional outbox. Missing workspaces fail closed instead of being created
implicitly in server mode.

## Consequences

- One pure function determines policy codes and ordering for both backends.
- Exact amount text remains available beside PostgreSQL NUMERIC values.
- Schema and rollback tests run without a service; an optional configured live
  test exercises a non-superuser role, RLS isolation, side effects, and exact
  SQLite result parity.
- That live test is skipped when the required DSN/application role is absent;
  code-level success alone does not establish deployed parity.
- Downgrade removes only the three additive migration-0016 tables.
