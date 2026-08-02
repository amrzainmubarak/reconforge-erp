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

The schema, linear migration, safe row conversion, and focused contract tests
are included in this slice.  A live PostgreSQL run is required before this
boundary can be promoted to `live_verified_current`; federation, API/UI route
coverage, cache invalidation wiring, and emergency-access policy remain open.

## Rollback

The downgrade refuses to remove any retained delegation rows.  Operators must
export or explicitly retire the evidence before a destructive rollback.
