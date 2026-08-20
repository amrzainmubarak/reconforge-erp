# ADR 0280: PostgreSQL policy snapshot conflict analysis

## Status

Accepted for the bounded Phase 4 IAM slice.

## Context

`enterprise-policy-conflict-analysis-v1` previously accepted only a local
approved snapshot. The server profile already owns PostgreSQL RBAC and service
account permissions under forced tenant RLS, but no read-only path connected
that authority to the deterministic analyzer.

## Decision

Add `PolicyAnalysisApplicationService` with a typed repository port and a
`PostgresPolicyAnalysisRepository` adapter. The adapter reads active user-role
permissions and enabled service-account permissions using tenant-bound,
parameterized SQL inside the existing `PostgresTenantBoundary` transaction.
The API exposes `POST /api/v1/admin/access/policy-analysis` with closed input,
human-only `security.policy.manage`, an independent `approved_by`, and an
explicit prior `approved_at` timestamp. The service delegates to the existing
analyzer and returns its replay/tamper-verifiable result without mutation.

## Scope and safety boundary

- Existing role, permission, session, and service-account tables are read only.
- Current PostgreSQL grants are tenant-wide analysis scopes; absence of
  entity/period/resource columns is represented explicitly as unscoped and can
  produce a privileged-scope finding.
- No role assignment, session revocation, cache invalidation, provider call,
  federation operation, or write-back occurs.
- The runtime claim is limited to synthetic single-node PostgreSQL under the
  non-privileged application role after the dedicated CI server-boundary gate.

## Rollback

The slice is additive and has no migration. Removing the route, adapter,
application service, tests, and documentation restores the prior API surface;
no persisted data requires conversion.
