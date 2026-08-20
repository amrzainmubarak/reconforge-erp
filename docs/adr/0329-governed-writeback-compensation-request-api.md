# ADR 0329: Compensation requests are actor-bound, scoped, and optimistic-versioned

## Status

Accepted — 2026-08-04

## Context

The write-back lifecycle already persisted proposals, maker-checker approval,
dispatch, and provider acknowledgement. A compensation transport now exists,
but callers still lacked a server/local API transition that records who asked
for compensation and why. Allowing a client to submit an unscoped or stale
request would make the reversal trail ambiguous and could overwrite a newer
lifecycle decision.

## Decision

Add `POST /api/v1/connectors/writeback/intents/{intent_id}/compensate` behind
the independent `connectors.writeback.compensate` human permission. The route:

1. binds tenant/workspace to the authenticated execution scope in server mode;
2. binds the requester to the authenticated actor and rejects the original
   maker as the compensation requester;
3. requires an optimistic `expected_version` and appends an immutable
   `compensation_requested` version;
4. stores a bounded reason, actor, and UTC request timestamp in the intent;
5. performs no provider I/O; transport dispatch remains a separately admitted
   operation with its own allowlist and acknowledgement checks; and
6. accepts an exact replay of the same actor/reason against the prior version
   without appending a duplicate version, while rejecting changed actor/reason
   inputs.

The local SQLite migration seeds the permission for the default `admin` and
`controller` roles. PostgreSQL tenants must provision the same permission
through the existing identity administration boundary; automatic cross-tenant
seeding is intentionally not performed by an Alembic migration because forced
RLS requires an explicit tenant context.

## Consequences

Compensation intent requests are auditable and race-safe across SQLite and the
PostgreSQL repository boundary. The actor metadata is additive and persisted
in the digest-bound JSON. A compatibility digest reader accepts legacy
intent rows created before the metadata fields existed. This does not claim
live ERP/bank reversal semantics, provider-specific accounting behavior,
automatic compensation, HA/DR, or production readiness.

## Rollback

Do not remove the migration or route while compensation intent evidence exists.
To roll back before adoption, stop at the prior application version and retain
the additive permission and append-only intent rows for forward migration.
