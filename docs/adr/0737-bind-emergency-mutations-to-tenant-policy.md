# ADR 0737: Bind emergency mutations to tenant policy context

- **Status**: Accepted
- **Date**: 2026-08-28
- **Decision owners**: ReconForge maintainers

## Context

The emergency-access route dependencies already checked the explicit
permission, human principal, and step-up assurance. The subsequent PostgreSQL
repository work was tenant-bound by RLS, but the route-level policy evidence
for request, approval, rejection, review, and administrator end actions did
not carry the authenticated tenant context. That weakened ABAC provenance even
though the database boundary remained tenant-scoped.

## Decision

Before each emergency mutation that uses a named administrative permission,
re-evaluate that permission through `enforce_server_tenant_permission` using
the validated request tenant. Apply this to request, approve, reject, review,
and administrator end paths. Keep target self-service activation/end paths
without a synthetic administrative permission; their existing human-session,
target, state, version, expiry, and repository checks remain authoritative.

## Consequences

- Emergency mutation policy evidence contains a bound tenant scope digest.
- A stale or mismatched tenant header fails closed before the repository
  operation; forced-RLS remains a second barrier.
- The route still has an explicit permission dependency, so route inventory and
  request-time authorization remain aligned.
- No workspace is invented for a tenant-wide emergency control.
- This is bounded policy-context hardening, not PAM, external IAM, or
  production-effectiveness evidence.

## Verification and rollback

The emergency helper unit test, live emergency API/repository tests when a
declared PostgreSQL DSN is available, full regression, Ruff, Mypy, Bandit,
pip-audit, package build, YAML, and diff checks verify E-1077. Rollback means
reverting the helper calls, test, ADR, and execution records together; do not
remove tenant binding from emergency mutation policy evidence.
