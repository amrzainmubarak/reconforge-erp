# ADR 0632: Keep the local Inventory Core API out of the PostgreSQL server profile

- Status: Accepted
- Date: 2026-08-26
- Scope: `reconforge.api.routes.inventory_core`

## Context

Inventory Core has a PostgreSQL repository and schema, but its current HTTP
router still invokes the local `InventoryCoreService`, which is backed by
SQLite. The generic `get_db` dependency can resolve a tenant-local SQLite file
when a PostgreSQL server identity is configured. That creates a dangerous
profile ambiguity: an authenticated server request could receive a successful
Inventory response from the wrong persistence plane instead of the configured
PostgreSQL domain.

## Decision

Add an explicit `get_inventory_local_db` dependency and use it for every
Inventory Core route. It rejects the PostgreSQL server identity profile with
HTTP `501 inventory_server_backend_unavailable` before opening SQLite. Local
mode continues to use the existing migrated SQLite path unchanged.

The PostgreSQL Inventory Core repository remains available for a later,
dedicated server route slice. That slice must bind request hierarchy, central
policy, RLS transaction scope, audit/outbox behavior, and runtime evidence
before the server API is enabled.

## Consequences

The server profile cannot silently read or mutate tenant-local Inventory Core
SQLite data. This is a fail-closed compatibility boundary, not a claim that
server Inventory Core is complete. Existing local CLI/API behavior remains
compatible, and the authorization route inventory remains closed.

## Rollback

Remove the explicit dependency and restore the local `get_db` dependency only
after a reviewed server Inventory adapter replaces the fallback. Do not
restore implicit SQLite access in the PostgreSQL server profile.
