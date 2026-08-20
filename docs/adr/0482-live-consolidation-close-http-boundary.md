# ADR 0482: Prove the PostgreSQL consolidation-close HTTP boundary

- Status: accepted
- Date: 2026-08-10
- Scope: `P4-PLAT-001`, consolidation-close server read boundary

## Decision

The PostgreSQL consolidation-close read surface must be exercised through the
actual FastAPI `TestClient`, PostgreSQL identity factory, service-account
credential, explicit workspace grant, replay verification, and forced-RLS
repository. The opt-in live test provisions two synthetic tenants, persists a
verified control-journal worksheet and run with a non-superuser,
non-BYPASSRLS role, and checks list/read responses plus workspace and
sibling-tenant denial. The repository read path must remove its internal
domain-object replay cache before API serialization.

The CI server-boundaries job invokes the HTTP contract explicitly. This proves
only the authenticated server read boundary and deterministic evidence
exposure; it does not introduce statutory posting, ERP write-back, live
consolidation sources, HA/DR, or a production claim.

## Rollback

Remove the live test, serialization-boundary fix, ADR, inventory reference,
manifest entry, and workflow invocation. Existing SQLite and PostgreSQL
control-journal lifecycle behavior remains unchanged.
