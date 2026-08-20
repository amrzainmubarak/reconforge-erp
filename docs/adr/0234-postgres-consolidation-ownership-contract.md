# ADR-0234: Add PostgreSQL consolidation ownership contract

- Status: accepted
- Date: 2026-08-02

## Context

The local ownership master from ADR-0233 needs an enterprise storage path, but
static adapter code must not be represented as live PostgreSQL parity. The
storage contract must preserve exact financial values, tenant isolation, and
immutable history.

## Decision

Add Alembic 0054 and a tenant-scoped PostgreSQL adapter. Use `NUMERIC` for
percentages, forced RLS on `app.tenant_id`, immutable update/delete triggers,
transaction-local scope setting, row locking for overlap checks, and a linear
downgrade. Classify the boundary `contract_only` until an unskipped disposable
non-superuser run proves migration, RLS, isolation, rollback, and restore.

## Evidence and limits

Schema, migration lineage, application-port signature, and actor fail-closed
tests pass. No live PostgreSQL DSN was used; no runtime parity or deployment
claim is made.
