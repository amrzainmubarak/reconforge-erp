# ADR 0632: Keep the local Inventory Core API out of the PostgreSQL server profile

- Status: Superseded by ADR 0634
- Date: 2026-08-26
- Scope: `reconforge.api.routes.inventory_core`

> This ADR records the safe interim boundary delivered by E-939. ADR 0634
> replaces it only for the explicitly implemented PostgreSQL server path;
> local SQLite compatibility and fail-closed behavior for an unconfigured
> server backend remain unchanged.

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

The PostgreSQL Inventory Core repository remained available for a later,
dedicated server route slice. That requirement was fulfilled in bounded form
by ADR 0634, which supersedes this interim decision for configured PostgreSQL
server requests.

## Consequences

Before ADR 0634, the server profile could not silently read or mutate
tenant-local Inventory Core SQLite data. That historical boundary remains the
fallback safety rule when the PostgreSQL server capability is unavailable.
Existing local CLI/API behavior remains compatible.

## Rollback

Remove the explicit dependency and restore the local `get_db` dependency only
after a reviewed server Inventory adapter replaces the fallback. Do not
restore implicit SQLite access in the PostgreSQL server profile.
