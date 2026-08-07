# ADR 0431: Keep PostgreSQL migration status fail-closed and lifecycle-safe

- **Date**: 2026-08-07
- **Status**: accepted

## Context

The hosted server-boundary matrix previously surfaced an unsupported Alembic
revision from the PostgreSQL operational status provider. The provider must
never treat an unknown database state as current, and its connection lifecycle
must be deterministic on success, rejection, and invalid caller input.

## Decision

Keep the explicit linear `POSTGRES_MIGRATION_REVISIONS` registry as the
application compatibility contract. Accept only a revision in that registry,
report the current head and pending suffix deterministically, close the
connection in every connected path, and reject a blank database locator before
opening a connection.

## Verification and boundary

Synthetic provider contracts cover current-head success, unknown-revision
rejection, connection closure, and blank-locator no-connect behavior. These
tests protect the application contract but do not replace a fresh hosted
Alembic upgrade against PostgreSQL.
