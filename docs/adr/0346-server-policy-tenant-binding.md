# ADR 0346: Bind every server-scoped policy check to the request tenant

- **Date**: 2026-08-05
- **Status**: Accepted

## Context

Workspace-scoped route adapters already pass the authenticated execution
hierarchy to the central policy helper. The helper accepted the tenant as an
adapter argument, however, so a future caller could accidentally supply a
sibling tenant while retaining a valid workspace grant.

## Decision

Make `enforce_server_scoped_permissions` compare its tenant argument with the
validated `X-ReconForge-Tenant` request header before evaluating policy. A
mismatch fails closed with `tenant_scope_denied`. Tenant-wide administration
continues to use the same helper with an intentionally absent workspace.

## Consequences

- All current server-scoped route families gain a centralized tenant-binding
  invariant without changing local SQLite behavior.
- Adapter code still owns workspace/entity selection and must continue to
  validate those fields before repository access.
- This does not complete worker/export/UI adoption, federation, distributed
  invalidation, live providers, or production IAM assurance.

## Verification and rollback

`tests/test_api_execution_scope.py` covers both matching and sibling-tenant
requests. Rollback removes the equality check, this ADR, its package entry and
the execution record; no migration or data rewrite is needed.
