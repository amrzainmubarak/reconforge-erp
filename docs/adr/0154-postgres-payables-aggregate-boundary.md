# ADR 0154: Keep PostgreSQL Payables as one governed aggregate boundary

- Status: Accepted
- Date: 2026-07-28

## Context

The Payables Application contract spans supplier governance, purchase-order
lifecycle, receipts, supplier invoices, deterministic three-way matching,
maker-checker approval, idempotency, and read models. Implementing invoice CRUD
alone would not preserve the current financial or workflow invariants.

## Decision

Use nine tenant-keyed PostgreSQL tables for suppliers, purchase orders and
lines, goods receipts and lines, supplier invoices and lines, three-way match
decisions, and idempotency responses. All parent relationships use composite
tenant keys and every table forces RLS.

Store monetary values exclusively as constrained `BIGINT` minor units. Store
quantities as unconstrained exact `NUMERIC` plus canonical text so calculations remain exact
and compatible output does not depend on driver formatting. Currency references
must resolve to active tenant currency masters. Mutations will append audit and
outbox evidence inside the same transaction.

## Consequences

- Migration 0021 is additive and child-first reversible.
- All 15 Application methods use the same tenant/workspace and evidence pattern.
- Payables is `live_test_available` in the PostgreSQL parity inventory because
  the complete lifecycle test exists but is skipped without configured service credentials.
- A configured non-superuser PostgreSQL run remains required before any current
  live claim.

## Rollback

Drop child tables before parents using migration 0021 downgrade. No SQLite data
is mutated. Weakening minor-unit storage, tenant-qualified foreign keys, RLS, or
atomic evidence is not an acceptable rollback.
