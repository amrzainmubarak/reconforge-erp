# Durable scheduler operations

## Current maturity

The scheduler is an experimental PostgreSQL application boundary. Migration
0047 supplies the durable schedule/job transaction; migration 0048 adds a
bounded long-running polling worker and optional redacted notification
requests. Evidence is synthetic and single-node. It is not an HA service or a
production-readiness claim, and there is no public CLI/API in this slice.

## Registration contract

A registration requires a tenant, workspace, optional generic entity scope,
versioned daily/weekly IANA schedule, explicit DST/misfire policy, whole-second
UTC cursor, and immutable durable-job template. Replaying the same version is
accepted only when the initial registration digest matches. Configuration
changes require a strictly higher version and atomically disable the prior
active version.

The initial cursor is retained separately from the advancing current cursor so
the registration digest remains independently verifiable after processing.

## Poll contract

`SchedulerApplicationService.process_due` is the bounded integration surface.
Callers must supply a validated tenant, stable worker identity, timezone-aware
whole-second UTC `now`, and a batch limit from 1 through 1,000. PostgreSQL uses
row locks with `SKIP LOCKED`; each selected schedule then runs under its own
workspace/entity RLS scope inside the same transaction.

For each due occurrence, the transaction creates or resolves one compatible
durable job, appends immutable dispatch evidence, advances the cursor according
to the misfire policy, and appends safe count-only audit evidence. Any conflict
or storage failure rolls back the job, dispatch, cursor, and audit writes.

## Failure handling

- Excess lookback: stop and review the cursor; no automatic skip or advance is
  performed.
- Durable-job identity conflict: treat as integrity failure; compare schedule
  version, job template digests, and existing job evidence before retrying.
- Concurrent empty poll: normal when another worker owns the eligible rows.
- Deferred catch-up: poll again with the same `now` or a later instant; the
  cursor resumes after the last committed occurrence.
- Notification delivery: 0048 atomically creates an outbox request only for an
  explicit active route subscription. External delivery is separately retried
  and at-least-once; it must not be inferred from successful job dispatch.

## Hosted polling

`PostgresSchedulerWorker` validates and bounds tenant enumeration, captures one
whole-second UTC instant per cycle, and opens a fresh connection per tenant.
Multiple single-node worker processes can safely contend through the existing
`SKIP LOCKED` transaction. This is not leader election, HA orchestration, or a
distributed scheduler guarantee.

Notification runtime, egress activation, dead-letter review, and replay are
documented in `docs/operations/notifications.md`.

## Migration and rollback

Upgrade with the normal Alembic path. Empty 0048 can downgrade to 0047, and an
empty 0047 can downgrade to 0046. Either migration refuses a non-empty evidence
boundary before dropping data. Retain a verified database backup and use an
approved migration plan rather than disabling either guard.

## Evidence queries

Use tenant/workspace/entity-scoped, read-only queries against
`reconforge.schedules`, `reconforge.schedule_dispatches`, and
`reconforge.schedule_events`. Do not log job payloads or raw financial records;
the scheduler evidence contains identities, timestamps, and bounded counts.
