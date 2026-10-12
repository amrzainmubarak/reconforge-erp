# ADR 0827: Fence outbox leases and retain recovery evidence

- Status: accepted; SQLite migration 53, PostgreSQL revision 0103, and verified
  SQLite backup/restore admission are integrated.
- Date: 2026-10-04
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

The storage guard admits only an initial `0/0` pending row. It rejects a direct
`0/2` insert, a direct pending-to-published edge, a generation jump, and every
delivery transition that does not originate from the required claimed
generation. A `2/2` compatibility watermark is historical evidence, never a
live lease: acknowledgement, failure, and pre-publication assertion all
require `lease_generation > lease_generation_floor`. An expired legacy lease
can only be recovered, after which its next claim is generation `3`.

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
and immutable-evidence triggers. Admission is a separate `BEFORE INSERT`
trigger: only the trusted `AFTER UPDATE` transition trigger at the required
trigger depth may append evidence; it binds tenant, event, hierarchy,
generation, attempt count, and current state to the parent row. Direct
application-role INSERT is rejected even if an ACL was granted accidentally.
SQLite enforces equivalent parent/state/history admission and a semantic
`(event_id, lease_generation, action)` unique key. The PostgreSQL key avoids a
new random-ID extension or sequence permission requirement.

`validate_outbox_fencing_storage` is wired into both repositories before they
accept storage. It verifies every visible retained parent/evidence pair,
rejects gaps, duplicates, malformed records, and evidence without a visible
parent, and deliberately does not enumerate an untrusted generation range.
It also binds each post-floor terminal action to the worker that claimed that
generation, and checks that terminal/replay actions can explain the retained
delivery state. A historical `2/2` parent may retain any pre-upgrade delivery
state without invented evidence; it cannot act as a live claim. The PostgreSQL
adapter reads the joined parent/evidence set in one statement snapshot so
concurrent claim commits cannot create a false continuity failure.

## Activation implementation

SQLite migration 53 is a frozen literal in
`reconforge.db.migration_53_outbox_fencing`. It runs every DDL statement,
historical `2/2` watermark, trigger, migration marker, and `PRAGMA user_version`
write in one `BEGIN IMMEDIATE` transaction. Its static identity test prevents a
future runtime schema helper from changing historical migration content, and its
fault-injection test proves rollback at the watermark, guard, and marker stages.

PostgreSQL revision `0103_pg_outbox_fencing` is likewise a frozen Alembic
literal following revision 0102. It requires a superuser or `BYPASSRLS` role
before an `ACCESS EXCLUSIVE` outbox lock, watermarks populated rows, preserves
forced RLS on evidence, and revokes direct evidence writes from `PUBLIC`. It
does not name or grant a deployment-specific application role: scoped evidence
`SELECT` with no direct `INSERT`, `UPDATE`, or `DELETE` remains an explicit
deployment access-control requirement and is exercised by the non-privileged
runtime fixture. The transition and admission functions are `SECURITY DEFINER`
with a closed `reconforge, pg_catalog` search path so the trigger can append
valid evidence without granting direct write access to that application role.
The downgrade refuses retained evidence or a non-default generation/floor;
recovery uses a verified pre-change backup instead of destructive schema
rollback.

The SQLite backup contract includes both fenced event fields and the complete
`outbox_delivery_evidence` child table in deterministic parent-before-child
order. A v53 source must contain the required tables, columns, and complete
guard bundle before backup succeeds. Restore removes that bundle only in the
unpublished temporary database, loads parent events then evidence, verifies the
complete retained state, reinstalls canonical guards, performs a foreign-key
check, then verifies again after migration to the latest local schema. A v52
backup remains readable: migration 53 assigns `2/2` to retained historical rows
without inventing evidence.

Both repositories reject a database lacking the fencing columns before operating.
The module manifest, SQLite and PostgreSQL migration tests, recovery/concurrency
tests, and backup/restore tests define the bounded acceptance surface.

## Evidence

On 2026-10-04, the integrated SQLite migration/backup command
`tests/test_outbox_fencing_migration.py tests/test_outbox_fencing_backup.py`
passed 15 synthetic cases. It covers frozen migration identity, atomic rollback
at each registered checkpoint, populated historical watermarks, deterministic
backup ordering, exact round-trip evidence, post-restore guard reinstatement,
checksum-valid missing/forged evidence rejection, and v52-to-v53 compatibility.
The existing SQLite delivery/recovery/continuity/worker command passed 51 cases.

The integrated live PostgreSQL command
`tests/test_postgres_outbox_fencing_migration.py
tests/test_postgres_outbox_fencing_recovery.py` passed against the configured
local disposable PostgreSQL instance and non-superuser/non-`BYPASSRLS`
application role. It covers the real 0102-to-0103 migration, populated
watermarking, forced-RLS evidence isolation, rejected direct evidence forgery,
security-definer trigger append, downgrade refusal, stale worker fencing, and
valid runtime transition behavior. Focused Ruff and Mypy also passed.

The database protects the fence and evidence structure, but a shared
PostgreSQL runtime role can still perform a structurally valid raw transition.
That role and the trusted server application remain the actor-identity and
authorization authority boundary; database guards do not turn the shared role
into separate human credentials.

On 2026-10-03, synthetic SQLite tests exercised historical upgrade marking,
same-label stale acknowledgement and failure refusal, explicit `2/2` legacy
lease refusal, expired unclaimed lease refusal, final-attempt terminal
recovery, two-connection claim ownership, application-service token
propagation, first-claim compatibility, fresh-worker-connection token
propagation, exact-update rollback, evidence-trigger rollback, immutable and
trigger-admitted evidence, direct `0/2` insert and pending-to-published
rejection, retained-evidence corruption refusal, terminal-state/action/worker
binding refusal, bounded 1,000-event recovery, and property-based continuity
validation: 42 tests passed.

On a disposable Docker PostgreSQL 17 Alpine instance with a separate
non-superuser/non-`BYPASSRLS` application role, 14 live tests passed. They
covered the same stale-label and terminal-recovery cases, explicit legacy
watermark refusal, `SKIP LOCKED` claim races, tenant/hierarchy evidence
isolation, app-role raw insert/state/evidence forgery rejection,
parent-hierarchy admission rejection, RLS migration-identity preflight,
evidence-write rollback, a populated historical upgrade, repeat installation,
immutable evidence, retained-evidence corruption refusal, and a 1,000-event
recovery profile. The profile drained ten batches of 100 plus an idempotent
final call; observed recovery-only wall time was 0.924943 seconds. The
equivalent SQLite profile observed 0.041081 seconds and an indexed search
using `idx_outbox_expired_lease`. PostgreSQL selected a sequential scan plus
sort for this 1,000-row forced-RLS profile; no index-selection claim is made.
These are bounded synthetic measurements on the named local environment, not
throughput, latency, capacity, or service-level claims.

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
