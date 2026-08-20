# ADR 0225: Reference database access is named-query and tenant-scoped

- Status: accepted
- Date: 2026-08-02

## Decision

Add a synthetic `reference-database-readonly` connector with two closed named
query profiles, exact HTTPS egress, runtime credential reference, explicit
tenant scope, bounded rows/cells, cursor pagination, stable ordering, duplicate
rejection, and exact Decimal row validation. Use an injected transport; never
accept SQL or arbitrary database identifiers at the connector boundary.

## Consequences

- Database connector contracts are executable without a live database or
  credentials, and SQL injection is structurally absent from the SDK surface.
- A real adapter must prove prepared statements, least-privilege roles,
  timeouts, cancellation, read consistency, provider retries, and migration
  compatibility before live use.
- The connector is read-only and cannot post, write back, or alter schema.

## Rollback

Remove the database connector module, tests, docs, ADR, exports, and manifest
entries. No database or external state is changed.
