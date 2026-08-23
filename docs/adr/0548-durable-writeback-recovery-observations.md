# ADR 0548: Persist durable write-back recovery observations

- **Status**: Accepted
- **Date**: 2026-08-22
- **Scope**: E-834 durable provider-status observations and reviewer drill-down

## Context

E-833 separated provider status observation from lifecycle mutation, but the
observation existed only in memory. A pending, rejected, not-found, or
unknown response must remain reviewable after a process crash and must be
bound to the immutable write-back proposal without changing that proposal's
history.

## Decision

Add `WritebackRecoveryObservationRecord` as a separate immutable evidence
record. It binds:

- tenant, workspace, intent, connector, and proposal digest;
- the inner provider outcome observation and its raw-body/response digests;
- actor and timezone-aware observation timestamp;
- deterministic observation id and evidence-node id.

Persist the record through backend-neutral repository methods in both:

- SQLite migration 43; and
- PostgreSQL Alembic revision `0090_pg_writeback_observations`.

Both stores enforce append-only UPDATE/DELETE refusal, scope isolation, JSON
column identity checks, idempotent replay, and application-level binding to a
persisted intent's connector, proposal digest, and idempotency key. The API
persists an observation before any accepted recovery transition and exposes a
read-only scoped observation list for reviewer drill-down.

## Rationale

Separate storage prevents evidence collection from rewriting financial
lifecycle history. The deterministic record id makes a retried persistence
operation safe while timestamp/actor differences remain separately auditable.
The evidence-node id gives later Evidence Graph materialization a stable node
identity without storing provider payloads, credentials, or customer rows.

## Verification

The local contract suite and API recovery tests pass. A disposable runtime
matrix passes on SQLite and exact PostgreSQL 16.14/17.10 images with the same
record digest, non-privileged role flags, tenant isolation, idempotent replay,
and direct UPDATE/DELETE refusal. Report:
`docs/execution/POSTGRES_WRITEBACK_OBSERVATION_MATRIX_2026-08-22.json`.

## Compatibility and rollback

The existing intent table and historical intent JSON remain unchanged. The
new schema is additive and can be downgraded by dropping only the observation
table and trigger. Removing the API read route would reduce observability but
would not alter write-back lifecycle state.

## Boundary

The matrix uses synthetic provider responses and one Docker host/failure
domain. It does not prove live vendor status semantics, accounting posting,
settlement, distributed HA, production credentials, or regulatory assurance.
