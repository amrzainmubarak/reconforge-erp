# ADR 0412: Durable jobs carry organization scope across storage modes

- **Date**: 2026-08-07
- **Status**: Accepted

## Context

Durable jobs already carried tenant, workspace, and entity lanes, while central
authorization and other PostgreSQL workers had an organization dimension. A
job claim or queue bound could therefore be selected without retaining the
organization that the policy decision authorized.

## Decision

Add an optional organization identifier to the durable-job aggregate,
submission, scheduler lane, and worker claim contracts. SQLite persists it via
schema migration 33 and includes it in bounded queue counts, replay identity,
backup import/export, and claim filters. PostgreSQL migration
`0075_pg_job_organization_scope` adds the nullable attribution column, a
scope-aware index, transaction-local defaults, and organization-aware RLS.
Repository transactions restore the exact hierarchy before every write,
lease, evidence, and replay read; legacy tenant/workspace jobs remain
compatible with an empty organization value.

## Verification and boundary

Focused durable-job, backup/restore, scheduler, migration-chain, and package
tests pass locally; live PostgreSQL execution remains capability-gated. This
is a durable-job isolation and provenance primitive, not distributed queue
fairness, provider IAM, HA/DR, or production readiness.

## Reversibility

SQLite downgrade is not implicit; restore from a pre-migration backup is
required before removing column 33. PostgreSQL downgrade drops the additive
column/index and restores the prior tenant/workspace/entity policy. Existing
legacy rows remain representable because the field is nullable in PostgreSQL
and defaults to empty in SQLite.
