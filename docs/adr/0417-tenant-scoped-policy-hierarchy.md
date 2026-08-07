# ADR 0417: Preserve organization/entity policy binding for tenant-scoped routes

- **Status:** Accepted
- **Date:** 2026-08-07
- **Scope:** Central server ABAC re-evaluation

## Context

Some PostgreSQL evidence contracts are intentionally tenant-scoped and call
`enforce_server_scoped_permissions` with `workspace_id=None`. The central
helper only derived organization headers when a workspace was present, so
tenant-scoped PPA, impairment, deferred-tax, and administrative surfaces could
skip organization/legal-entity policy binding even when those headers existed.

## Decision

Normalize and bind optional `X-ReconForge-Organization` and
`X-ReconForge-Legal-Entity` headers for every server-scoped policy call,
including tenant-only calls. Explicit scope arguments must match headers;
legal-entity scope without an organization is rejected with the stable
`organization_scope_required` error. Workspace behavior and local SQLite
compatibility remain unchanged.

## Evidence boundary

Execution-scope tests prove tenant-scoped acceptance, parent-required refusal,
and existing workspace mismatch behavior. The dependent route contracts remain
tenant-only at the PostgreSQL data model; this ADR does not claim multi-entity
row isolation, statutory accounting, or production IAM.

## Rollback

Remove the generalized header binding, focused tests, ADR, manifest entry, and
execution records. No schema or data rollback is required.
