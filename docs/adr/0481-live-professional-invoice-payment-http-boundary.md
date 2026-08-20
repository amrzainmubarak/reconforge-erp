# ADR 0481: Prove the PostgreSQL professional invoice/payment HTTP boundary

- Status: accepted
- Date: 2026-08-10
- Scope: `P4-PLAT-001`, professional invoice/payment server persistence

## Decision

The professional invoice/payment server contract must be exercised through
the actual FastAPI `TestClient`, PostgreSQL identity factory, service-account
credential, scope grant, and forced-RLS repository. The opt-in live test
provisions two synthetic tenants, persists one replay-verified report, checks
list/read responses and server source metadata, and checks workspace and
sibling-tenant denials with a non-superuser, non-BYPASSRLS role.

The CI server-boundaries job invokes both the repository and HTTP test files.
The contract remains capability-gated when PostgreSQL is absent. This proves
only API and tenant-isolation behavior; it does not introduce billing-provider
authentication, revenue recognition, posting, write-back, HA/DR, or a
production claim.

## Rollback

Remove the live test, ADR, and workflow invocation. Existing SQLite and
PostgreSQL repository behavior is unchanged.
