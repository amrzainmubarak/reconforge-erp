# ADR 0736: Require explicit permission for emergency-access requests

- **Status**: Accepted
- **Date**: 2026-08-28
- **Decision owners**: ReconForge maintainers

## Context

The PostgreSQL emergency-access request endpoint accepted any authenticated
identity. The repository already constrained the request to the current user,
limited grants to an eligible financial/operational registry, required an
independent approver, and bound activation to a stepped-up session. However,
request creation itself was classified as identity-only in the API inventory.
That left a mutation capable of initiating sensitive temporary authority
outside the central RBAC/ABAC permission contract.

## Decision

Require the tenant-defined `security.emergency.request` permission through the
existing central `require_permission` dependency. Register the permission as
human-only and privileged step-up protected. Remove emergency request creation
from the identity-only route allowlist. Preserve the existing self-target,
maker-checker approval, independent review, session binding, expiry, audit
event, and forced-RLS repository controls.

## Consequences

- A user must have an explicit tenant permission and recent human step-up
  before submitting an emergency-access request.
- Service accounts cannot submit emergency-access requests through the central
  policy engine.
- Existing PostgreSQL tenants must register and grant the new permission; no
  migration silently grants emergency authority.
- The local SQLite identity surface and the separate approval/review contracts
  are unchanged.
- This is a bounded authorization hardening. It does not establish PAM,
  external IAM, universal MFA, or production effectiveness.

## Verification and rollback

The route-inventory, policy, emergency API/repository, full Python regression,
Ruff, Mypy, Bandit, pip-audit, package build, YAML, and diff checks are the
verification gates for E-1076. Rollback means reverting E-1076, ADR 0736,
the route contract, policy registry, fixtures, and execution evidence together;
permissionless emergency requests must not be restored as the default posture.
