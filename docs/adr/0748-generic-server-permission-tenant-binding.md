# ADR 0748: Bind generic server permission dependencies to tenant scope

- Status: Accepted
- Date: 2026-08-28
- Scope: API server authorization context

## Context

The server-mode `require_permission` and `require_any_permission` dependencies
already authenticated a principal and evaluated its permission contract. Their
policy contexts did not, however, include the tenant selected and validated by
the server authentication boundary. Scoped route dependencies performed a
second explicit check, but routes relying on the generic dependency could lose
the connection between the authenticated tenant and the policy decision.

## Decision

When PostgreSQL server identity is enabled, both generic permission dependency
families must include the validated request tenant in `PolicyEvaluationContext`
and pass the principal's `authorized_tenant_ids` as the grant set. The named
compatibility fallback for legacy injected principals without a bound tenant
uses the current validated tenant only when a real principal is present. A
bound principal whose tenant grant does not contain the request tenant is
denied by the central policy engine before the route handler.

The dependency response remains the existing sanitized `permission_denied`
contract; the audited policy decision retains the precise
`tenant_scope_denied` reason.

## Rationale

Generic permission checks are still authorization boundaries, even when a
route later performs a more specific resource check. Carrying tenant scope at
this boundary prevents identity-only authorization contexts and keeps policy
evidence tied to the authenticated request tenant. The fallback is limited to
the existing test/compatibility seam and is not an independent tenant-membership
or IAM mechanism.

## Verification

`tests/test_api_dependencies.py` covers both the all-permission and any-
permission dependency modes with a sibling-tenant principal. The focused API
authorization suite and the full Python regression pass; Ruff, Mypy, Bandit,
package build, YAML parsing, and diff checks are release gates for this slice.

## Compatibility and rollback

Local SQLite dependency behavior is unchanged. Server-mode requests already
require the tenant header during authentication. Revert E-1088, this ADR, the
dependency/test changes, the manifest entry, and execution records together.
