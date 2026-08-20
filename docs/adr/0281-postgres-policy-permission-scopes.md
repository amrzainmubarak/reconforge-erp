# ADR 0281: PostgreSQL policy permission scopes are immutable and dimension-bound

## Status

Accepted for the bounded Phase 4 IAM scope-projection slice.

## Context

The policy conflict analyzer already understands workspace, entity, period,
region, and data-classification overlap, but the PostgreSQL role-permission
schema previously exposed only tenant-wide grants. Treating every grant as a
tenant wildcard made a review artifact unable to distinguish a bounded grant
from an overly broad one.

## Decision

Add Alembic migration `0058_pg_policy_permission_scopes` with an immutable,
forced-RLS `identity_role_permission_scopes` table. Each active row binds one
role permission to at least one bounded dimension and keeps stable actor,
lifecycle, and revocation evidence. The policy snapshot adapter left-joins
active scope rows, groups permissions by identical scope, and preserves an
unscoped tenant wildcard when no row exists.

## Safety boundary

- Scope rows are read by policy analysis; no route or job automatically adopts
  them as universal authorization enforcement.
- Amount floors/ceilings remain central-policy inputs and are not silently
  represented by this table.
- Updates may only perform one independent active-to-revoked transition;
  deletes and identity/dimension mutation fail closed.
- Runtime evidence is limited to the synthetic single-node PostgreSQL CI
  service under the non-privileged application role; federation, distributed
  invalidation, and complete route/job/export/UI adoption remain open.

## Rollback

Downgrade refuses while scope evidence exists. After an explicit governed
retention decision and empty table, the migration can be reversed without
rewriting prior role-permission records.
