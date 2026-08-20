# ADR 0348: Bind tenant-wide audit and security views to central policy

- **Date**: 2026-08-05
- **Status**: Accepted

## Context

The PostgreSQL audit browsing/verification and security-center routes are
tenant-wide operational views. Their normal FastAPI permission dependencies
must be followed by a request-time central-policy check before the repository
is opened; otherwise a raw permission snapshot could be treated as sufficient
authority for the selected tenant.

## Decision

Re-evaluate `audit.read` before audit browsing, `audit.verify` before chain
verification, and `security.center.read` before the security overview. Each
check binds to the validated request tenant and passes `workspace_id=None`
because these projections are not workspace-scoped.

## Consequences

- Tenant-wide operational views now use the same fail-closed central policy
  boundary as tenant administration and PPA evidence.
- Local SQLite behavior and redaction contracts remain unchanged; the boundary
  is active only when the PostgreSQL server identity profile is enabled.
- This does not establish complete worker/export/UI policy adoption, federation,
  distributed invalidation, independent HA/DR, compliance, or production IAM.

## Verification and rollback

The audit-administration, security-center, PostgreSQL security-center and full
server-identity tests remain green. Rollback removes the helper calls, ADR,
manifest entry, and execution records; no schema or data rewrite is required.
