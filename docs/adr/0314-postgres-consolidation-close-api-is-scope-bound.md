# ADR 0314: Bind the PostgreSQL consolidation-close API to execution scope

- **Status:** Accepted
- **Date:** 2026-08-04
- **Decision owners:** ReconForge maintainers

## Context

The local consolidation-close drill-down API already replay-verified periods,
runs, journals, effects, and certification metadata. The PostgreSQL adapter
had the same persistence contract, but the API surface did not select it in
server mode and was absent from the authorization inventory. A tenant-only
transaction boundary is insufficient for a caller holding grants for only one
workspace: a corrupted or incorrectly filtered repository response must not be
returned from a sibling workspace.

## Decision

Add a request-scoped PostgreSQL consolidation-close adapter. Every server
request resolves the authenticated tenant/workspace/organization/entity scope
through `request_execution_scope`, passes that scope to
`PostgresTenantBoundary`, and queries by the authorized workspace. Detail and
certification routes replay-verify the run and fail closed if the returned
workspace differs; list routes verify every returned record. Local SQLite
behavior remains unchanged. The eight routes are included in the startup
authorization inventory and retain their existing finance permissions.

## Boundary

This closes API/backend parity and hierarchy isolation for the existing
control-journal evidence. It is not statutory consolidation, live ERP/bank
integration, external write-back, distributed IAM, HA/DR, or production
readiness evidence.

## Rollback

Remove the adapter, server branches, inventory inclusion, tests, ADR, and
manifest entry. Existing SQLite routes and PostgreSQL repository data remain
compatible because no schema or persisted representation changes.
