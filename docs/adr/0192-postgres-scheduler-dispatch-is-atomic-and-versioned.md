# ADR 0192: PostgreSQL scheduler dispatch is atomic and versioned

## Status

Accepted on 2026-07-29.

## Context

The pure schedule contract in ADR 0191 can identify due local-wall-clock
occurrences, but it cannot survive a process crash or coordinate multiple
workers. Persisting a cursor separately from job submission would permit either
a lost occurrence or a duplicate business effect. Schedule edits also need a
replayable identity rather than in-place mutation.

## Decision

- Migration 0047 stores immutable schedule versions, a monotonic current
  cursor, the immutable initial cursor, and a digest over the complete initial
  registration. A higher version atomically supersedes the prior active
  version; an existing version accepts only an identical replay.
- Tenant-wide discovery uses `FOR UPDATE SKIP LOCKED`. After claiming a row,
  the same transaction narrows to its workspace and generic entity scope
  before it writes a job, dispatch evidence, cursor, or audit event.
- Every occurrence uses the ADR 0191 digest as its idempotency key. Its durable
  job identity is derived from that digest, and the configured job type is
  preserved in the existing durable-job idempotency-scope field.
- Durable-job submission, immutable occurrence-to-job evidence, cursor advance,
  and a bounded audit event commit in one PostgreSQL transaction. The cursor
  advances only after every selected occurrence is resolved to exactly one
  compatible durable job and dispatch row.
- Schedule configuration, dispatch rows, and audit rows are append-only.
  Mutable schedule state is limited to monotonic cursor/version changes and
  one-way supersession.
- Migration downgrade is allowed only when the scheduler tables are empty. A
  non-empty downgrade fails before any schema mutation and requires an approved
  backup/data-migration plan.

## Consequences

- Concurrent workers can safely poll the same tenant without sharing a process
  leader. Business effects remain at-least-once at the worker boundary and rely
  on the durable job's idempotency contract; no exactly-once transport claim is
  made.
- Excess lookback remains an explicit operator-review failure and never moves
  the cursor silently.
- PostgreSQL is the only persistence adapter in this slice. A hosted polling
  runtime, notification transports, allowlists, redaction, operational UI, and
  task exit audit remain later P3-ENT-005 slices.

## Rollback

On an empty installation, downgrade 0047 to 0046 removes the three scheduler
tables and their functions. On a non-empty installation, the migration refuses
the downgrade. Operators must first retain a verified database backup and use
an approved forward data migration; already-created durable jobs are not
deleted by the scheduler migration.
