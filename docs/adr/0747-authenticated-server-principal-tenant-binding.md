# ADR 0747: Bind authenticated server principals to tenant scope

- Status: Accepted
- Date: 2026-08-28
- Decision owners: identity-governance and security maintainers

## Context

The PostgreSQL identity operation authenticates a user or service-account
credential against the tenant selected by the request boundary. The resulting
AuthenticatedServerRequest carried permissions and workspace/organization/
legal-entity grants, but it did not preserve the authenticated tenant in the
typed principal. Scoped policy helpers consequently reconstructed the tenant
grant from the request-selected tenant. The existing request/header and
transaction-local RLS checks were separate barriers, but the policy context did
not make the authentication-to-tenant binding explicit.

## Decision

Carry the validated tenant through AuthenticatedServerRequest and preserve it
as ServerPrincipal.authorized_tenant_ids. When a server principal contains a
tenant binding, server-scoped policy helpers must reject a different tenant
before policy evaluation and must pass the bound grant into the policy context.
The operations queue policy context follows the same rule. Older tuple and test
seams that do not provide the optional field retain an explicit compatibility
fallback; real PostgreSQL-authenticated requests always populate the binding.

## Consequences and boundaries

The typed principal now preserves authentication provenance through the request
and makes the tenant grant visible in policy evidence. This is defense in depth
against future context-construction drift and does not replace request tenant
validation, PostgreSQL RLS, scope grants, or central policy evaluation. It does
not independently prove tenant membership, external IAM correctness,
distributed revocation, cross-region behavior, or production authorization
effectiveness.

The optional compatibility fallback avoids breaking existing local fixtures and
legacy tuple adapters. It must not be used to claim a tenant binding when the
real server identity path failed to populate the authenticated request object.

## Verification and rollback

The focused scope, operations, server-identity, and foundation tests cover
tenant propagation and reject a principal bound to a sibling tenant. Ruff and
Mypy pass for the changed Python files; the full regression and release-quality
gates remain required. Rollback is a source-level revert of E-1087, its tests,
manifest entry, execution records, and this ADR; no schema or persisted-data
change is involved.
