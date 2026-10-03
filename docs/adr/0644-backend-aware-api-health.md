# ADR-0644: Make API health backend-aware

- Status: Accepted
- Date: 2026-08-26
- Scope: E-951

## Context

`GET /api/v1/health` was implemented for the Local Profile and always called
the SQLite path resolver. When PostgreSQL Server Profile was enabled, that
route could report `reconforge-local-api`, inspect a tenant SQLite filename,
and expose the local migration version even though authenticated business and
identity boundaries were configured for PostgreSQL. This made an operational
probe materially misleading and could hide pending PostgreSQL migrations.

## Decision

Branch the unauthenticated health probe on the explicit server capability.
Local Profile keeps its compatible SQLite response. Server Profile reads the
PostgreSQL Alembic revision through the existing
`PostgresMigrationStatusProvider`, returns `reconforge-server-api`, identifies
the backend as PostgreSQL, and uses the redacted `server-managed` path
summary. Server health is `ok` only when the migration state is readable and
has no pending revisions; connection, driver, and migration failures return a
non-diagnostic `degraded` response without exposing DSNs or raw errors.

## Consequences

- Load balancers and operators no longer receive a local/SQLite health claim
  from a PostgreSQL Server Profile.
- A reachable but migration-incomplete server is visibly degraded rather than
  being presented as ready.
- The endpoint remains unauthenticated and intentionally returns HTTP 200 for
  liveness-compatible monitoring; readiness consumers must inspect `status`
  and `database.pending_migrations`.
- This does not prove PostgreSQL schema completeness for every module, HA/DR,
  external identity, capacity, production readiness, compliance, or
  certification.

## Rollback

Revert the route and test/doc changes in this slice. No schema, migration, or
persisted data changes are introduced.
