# ADR 0345: Re-evaluate tenant-wide administration permissions at the server boundary

- **Date**: 2026-08-05
- **Status**: Accepted

## Context

PostgreSQL identity, role, scope-grant, and security-retention administration
are tenant-wide operations. Their normal FastAPI dependencies already require
the correct human permission and step-up assurance, but the route adapters did
not consistently re-evaluate the same permission immediately before entering
the repository transaction. Reusing a synthetic workspace scope would be
incorrect because these resources intentionally have no workspace key.

## Decision

Add `enforce_server_tenant_permission`, a central-policy boundary that binds
the requested tenant to `X-ReconForge-Tenant`, preserves the existing human
step-up and service-account restrictions, and evaluates with no workspace
scope. Adopt it in the access-administration, identity-administration,
scope-grant, and security-governance route families before repository access.
Keep local SQLite compatibility unchanged and retain the existing
workspace-scoped helper for business resources.

## Consequences

- Tenant-wide administration now has request-time central-policy evidence and
  cannot accidentally authorize a sibling tenant through a caller-supplied
  tenant argument.
- Workspace-scoped business routes remain unchanged; no synthetic workspace
  grants are introduced.
- PostgreSQL live provider/federation, distributed invalidation, and complete
  worker/export/UI policy adoption remain open.

## Verification and rollback

`tests/test_api_execution_scope.py` proves tenant-wide allow and sibling-tenant
refusal. The access, identity, and security route regressions remain green.
Rollback removes the helper adoption, this ADR, and the execution evidence;
no migration or data rewrite is required.
