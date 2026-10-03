# ADR 0827: Fence outbox leases and retain recovery evidence

- Status: proposed; activation is blocked on the migration and backup integration
  listed below.
- Date: 2026-10-03
- Scope: SQLite and PostgreSQL transactional-outbox delivery ownership, crash
  recovery, and retained delivery evidence.

## Context

`worker_id` identifies a process label, not one lease.  A process can crash,
be restarted with the same label, or continue after its lease has expired.  The
previous delivery model could distinguish neither the stale acknowledgement nor
the stale failure update from the current owner's update when both used the
same worker label.

Expiry must also consume the final permitted delivery attempt.  Otherwise a
crash on the final attempt can be recovered indefinitely.  A state change
without retained evidence also leaves an operator unable to distinguish a
normal failure, an expired lease, and an explicit replay.

## Decision

Each `outbox_events` row gains two additive fields:

- `lease_generation`: a non-negative monotonic fencing token.  A successful
  claim increments it exactly once.
- `lease_generation_floor`: either `0` for rows created after activation or
  `2` for pre-existing rows whose historical claims cannot be reconstructed.

The migration assigns every populated pre-fencing row generation and floor
`2`; it does not invent historical claims.  A next successful claim therefore
has generation `3`.  A newly created row begins at `0/0` and its first claim
has generation `1`.

Claim acknowledgement, failure recording, and the pre-publication
`assert_claim` check require the exact live `(event_id, worker_id,
lease_generation)` tuple.  The legacy omitted-generation argument is accepted
only as generation `1`, which can acknowledge only a current first claim; it
cannot acknowledge a populated pre-fencing row or a reclaimed event.

Both repositories recover only a bounded, ordered expired batch.  Recovery
releases a retryable claim or changes a terminal claim to the dead-letter
state at the configured ceiling.  It never grants another delivery attempt.
SQLite acquires `BEGIN IMMEDIATE`; PostgreSQL uses tenant- and hierarchy-scoped
`FOR UPDATE SKIP LOCKED` candidates.  The expiry queries use the additive
`idx_outbox_expired_lease` index.

Each state transition appends one immutable `outbox_delivery_evidence` row in
the same database transaction.  The row records the event, exact generation,
action (`claimed`, `published`, `failed`, `expired`, or `requeued`), worker,
timestamp, and attempt count.  SQLite blocks UPDATE and DELETE using triggers.
PostgreSQL uses a semantic primary key
`(tenant_id, event_id, lease_generation, action)`, forced tenant/hierarchy RLS,
and a trigger that rejects UPDATE and DELETE.  The PostgreSQL key avoids a
new random-ID extension or sequence permission requirement.

`validate_outbox_delivery_evidence` verifies every post-floor claimed
generation exactly once, rejects gaps and duplicates, and deliberately does
not enumerate an untrusted generation range.

## Required integration before activation

This change deliberately contains no migration revision and no backup-router
change.  It must not be enabled by application code until all of the following
are committed and tested together.

1. Register `SQLITE_OUTBOX_FENCING_MIGRATION_SQL` from
   `reconforge.infrastructure.outbox_fencing_schema` after the existing SQLite
   outbox-delivery migration.  The migration must add
   `lease_generation` and `lease_generation_floor`, create
   `outbox_delivery_evidence`, its index, the immutable-evidence triggers, and
   `idx_outbox_expired_lease`.  A populated-upgrade fault test must prove that
   the entire SQLite migration either commits or leaves the prior schema
   unchanged.
2. Add one forward-only Alembic revision after the current PostgreSQL head
   which executes `POSTGRES_OUTBOX_FENCING_SCHEMA_SQL`.  It must run after the
   existing outbox application and hierarchy/RLS schema.  It must grant the
   application role `SELECT, INSERT, UPDATE, DELETE` on
   `reconforge.outbox_delivery_evidence`, preserve forced RLS, and prove a
   non-superuser/non-`BYPASSRLS` fresh and populated upgrade.  Its downgrade
   must refuse to discard non-empty retained delivery evidence; recovery is a
   verified pre-upgrade restore, not a destructive downgrade.
3. Extend the SQLite backup/restore contract to include both new
   `outbox_events` fields and the full `outbox_delivery_evidence` table.
   Restore parent events before evidence.  A backup from before activation
   must restore with an explicit `2/2` historical watermark, while a
   post-activation backup must retain exact evidence and pass
   `validate_outbox_delivery_evidence`.  The backup format/version and
   compatibility reader must reject incomplete evidence rather than silently
   reset generations.
4. Make fresh schemas include the additive fields, update schema inventory and
   package manifests, and run SQLite/PostgreSQL upgrade, restore, concurrency,
   and rollback admission tests before exposing the fenced worker as generally
   available.

Until those steps land, `SQLiteOutboxRepository` intentionally rejects a
database that lacks the two fencing columns.  This makes a partially deployed
binary/schema combination visible rather than silently operating without the
new ownership invariant.

## Evidence

On 2026-10-03, synthetic SQLite tests exercised historical upgrade marking,
same-label stale acknowledgement and failure refusal, expired unclaimed lease
refusal, final-attempt terminal recovery, two-connection claim ownership,
application-service token propagation, first-claim compatibility,
fresh-worker-connection token propagation,
exact-update rollback, evidence-trigger rollback, immutability, bounded
1,000-event recovery, and property-based continuity validation: 31 tests
passed.

On a disposable Docker PostgreSQL 17 Alpine instance with a separate
non-superuser/non-`BYPASSRLS` application role, 11 live tests passed.  They
covered the same stale-label and terminal-recovery cases, `SKIP LOCKED` claim
races, tenant/hierarchy evidence isolation, evidence-write rollback, a
populated historical upgrade, repeat installation, immutable evidence, and a
1,000-event recovery profile.  The profile drained ten batches of 100 plus an
idempotent final call; observed recovery-only wall time was 0.676690 seconds.
The PostgreSQL plan used `idx_outbox_expired_lease`.  The equivalent SQLite
profile observed 0.022337 seconds and an indexed search using
`idx_outbox_expired_lease`.  These are bounded synthetic measurements on the
named local environment, not throughput, latency, capacity, or service-level
claims.

## Transport boundary

The database fence prevents a stale worker from changing local delivery state.
`assert_claim` is the last local check before a publisher call, but a lease can
expire after that check and before or during an external call.  A non-fencing
transport can therefore receive a duplicate publication after a crash or lease
race.  This is bounded at-least-once delivery, not exactly-once transport.

An external sink must receive the stable event identity and generation as its
own idempotency/fencing input, or use a durable consumer receipt, before an
exactly-once business-effect claim can be made.  This decision does not add a
broker, a remote provider protocol, queue HA, cross-host recovery, or a
production performance claim.  A privileged database owner remains a trusted
operator boundary.

## Rollback

Stop workers, retain a verified pre-change backup, and keep a compatibility
reader for rows carrying the new columns and evidence.  Do not delete evidence,
reset generations, or downgrade a populated evidence table to make rollback
appear successful.  Restore is permitted only through the verified backup path
defined by the required integration work.
