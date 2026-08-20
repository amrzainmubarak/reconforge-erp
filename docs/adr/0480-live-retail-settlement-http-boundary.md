# ADR 0480: Prove the PostgreSQL retail evidence HTTP boundary

- Status: accepted
- Date: 2026-08-10
- Scope: `P4-PLAT-001`, retail settlement server persistence

## Decision

The retail settlement server contract must be exercised through the actual
FastAPI `TestClient`, PostgreSQL identity factory, service-account credential,
scope grant, and forced-RLS repository. The live test provisions two synthetic
tenants, persists one replay-verified settlement report, verifies list/read
responses and server source metadata, and verifies workspace and sibling-tenant
denials. The disposable PostgreSQL role is non-superuser and non-BYPASSRLS.

The CI server-boundaries job invokes both the repository and HTTP test files.
The test remains opt-in when no PostgreSQL service is configured. This is an
API/tenant-isolation contract only: no processor authentication, settlement
finality, accounting posting, ERP write-back, HA/DR, or production claim is
introduced.

## Rollback

Remove the live test and its workflow invocation. Existing local SQLite and
PostgreSQL repository contracts remain unchanged.
