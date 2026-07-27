# ADR-0108: Backend-aware operational diagnostics

- Status: Accepted
- Date: 2026-07-27
- Scope: P1-PLAT-002

## Decision

Make deployment mode an explicit repository capability. The Application
service must not hard-code `local_only=true`. SQLite returns true; PostgreSQL
returns false while preserving the existing response key for compatibility.

Add tenant-scoped PostgreSQL operational job/error tables with forced RLS and
an adapter that returns the same sanitized record shapes as SQLite. Read audit
health through the shared PostgreSQL domain audit verifier. Resolve PostgreSQL
migration status through an explicit ordered revision registry and Alembic's
database state, without passing a DSN into Application code.

## Consequences

- Health output no longer mislabels server deployment as local-only.
- Integer SQLite and string Alembic revisions are both supported explicitly.
- Record-shape parity and tenant isolation are live-tested.
- This slice does not prove that every future writer redacts sensitive data;
  writer-side classification/redaction remains a separate security gate.
