# ADR 0012: Bounded database-per-tenant API routing

## Status

Accepted as an optional self-hosted foundation; not a hosted readiness claim.

## Context

ReconForge currently persists local workflows in SQLite and does not yet have a
PostgreSQL/RLS repository layer. A server deployment must not imply that a token or
request can select another tenant's database through a path or header trick.

## Decision

Add an opt-in `TenantDatabaseRouter` and `create_api_app(..., tenant_db_root=...)`
mode. In this mode:

- every database-backed request requires `X-ReconForge-Tenant`;
- tenant IDs are restricted to lowercase letters, numbers, hyphens, and underscores;
- the resolved database is a fixed `<tenant_id>.db` child of the configured root;
- traversal, symlinked roots, missing databases, and invalid IDs are rejected;
- authentication and sessions are resolved only in the selected tenant database;
- the default single-database local mode remains backward compatible.

## Consequences

This provides a testable database-per-tenant boundary for bounded self-hosted
deployments. It does not provide shared-schema PostgreSQL isolation, row-level
security, centralized identity, object-storage isolation, worker propagation, or a
tenant catalog. Those remain separate release gates and must not be inferred from
this implementation.

## Verification

`tests/test_tenant_isolation.py` verifies missing-scope rejection, traversal
rejection, tenant-local authentication, and cross-tenant token rejection.
