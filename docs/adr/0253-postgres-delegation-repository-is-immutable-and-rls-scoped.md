# ADR 0253: PostgreSQL delegation repository is immutable and RLS-scoped

## Status

Accepted for the Phase 4 enterprise-identity slice.

## Decision

Temporary policy delegations are persisted in a tenant/workspace-scoped
`policy_delegations` table.  The migration enables and forces PostgreSQL row
level security using `app.tenant_id`.  A database trigger rejects deletes and
all updates except one active-to-revoked transition performed by an actor
different from the delegator.  The repository validates the typed
`DelegationGrant`, binds an explicit timezone-aware evaluation instant, and
keeps transaction ownership with its caller.

## Evidence and limits

The schema, linear migration, safe row conversion, focused contract tests, and
CI server-boundaries run `30771736208` are included in this slice. The runtime
evidence is synthetic and single-node; federation, API/UI route coverage,
cache invalidation wiring, and emergency-access policy remain open.

## Rollback

The downgrade refuses to remove any retained delegation rows.  Operators must
export or explicitly retire the evidence before a destructive rollback.
