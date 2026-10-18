# Outbox lease-fencing recovery profile v1

Date: 2026-10-03
Status: synthetic local evidence only

## Workload

The profile seeds 1,000 synthetic events, claims all of them, expires those
claims, then invokes real repository recovery in batches of 100.  It requires
ten productive calls and one final idempotence call returning zero.  Every row
is at the terminal attempt ceiling, so recovery must create exactly 2,000
evidence rows: one `claimed` and one `expired` record per event.

It excludes provisioning, seeding, initial claims, backup/restore, publisher
calls, remote transport, and general queue throughput from the measured wall
time.

## SQLite evidence

The local Python 3.14.6 profile ran against a temporary SQLite file after
SQLite migration 53 was applied:

```text
backend=sqlite events=1000 batch_limit=100 calls=11 recovered=1000
largest_batch=100 recovery_wall_seconds=0.041081
```

`EXPLAIN QUERY PLAN` reported:

```text
SEARCH outbox_events USING INDEX idx_outbox_expired_lease (locked_at>? AND locked_at<?)
```

The focused SQLite recovery/race/evidence and continuity suite completed 42
tests successfully. This run includes initial-state and transition admission,
legacy-watermark refusal, forged-evidence rejection, retained-storage
continuity verification, and final-state/action/worker-binding verification.
The profile does not measure cross-process publisher latency, storage
durability beyond SQLite's selected local settings, or a general capacity
limit.

## PostgreSQL evidence

A disposable PostgreSQL 17 instance used a separate non-superuser/non-
`BYPASSRLS` application role. It was migrated through Alembic revision
`0103_pg_outbox_fencing` for the bounded integration profile.

```text
backend=postgresql events=1000 batch_limit=100 calls=11 recovered=1000
largest_batch=100 recovery_wall_seconds=0.924943
```

For this 1,000-row disposable run, `EXPLAIN (FORMAT JSON)` selected a
sequential scan plus sort after evaluating the forced-RLS predicates. The
additive `idx_outbox_expired_lease` exists and SQLite selected its equivalent
index, but this PostgreSQL run is not evidence that its planner will select the
index at this cardinality or scope. The live suite passed 14 tests, including
same-label stale acknowledgement refusal, explicit legacy-watermark refusal,
final-attempt recovery, `SKIP LOCKED` ownership, RLS isolation, app-role raw
insert/state/evidence forgery rejection, hierarchy binding, trigger rollback,
retained-evidence corruption refusal, populated upgrade marking, and this
profile.

These measurements apply only to this synthetic single-node environment.  They
are not a broker benchmark, external delivery result, HA/DR test, capacity
claim, or production service objective.

## Reproduction

Run the focused suites against a disposable PostgreSQL server with a separate
application role. The SQLite and PostgreSQL migration/backup suites are part of
the current acceptance surface.

```powershell
python -m pytest tests/test_outbox_fencing_migration.py tests/test_outbox_fencing_backup.py tests/test_outbox_fencing_recovery.py tests/test_outbox_evidence_continuity.py -q -ra

$env:RECONFORGE_TEST_POSTGRES_ADMIN_DSN='postgresql://postgres:***@127.0.0.1:5432/postgres'
$env:RECONFORGE_TEST_POSTGRES_DSN='postgresql://reconforge_app:***@127.0.0.1:5432/postgres'
$env:RECONFORGE_TEST_POSTGRES_APP_USER='reconforge_app'
python -m pytest tests/test_postgres_outbox_fencing_migration.py tests/test_postgres_outbox_fencing_recovery.py -q -ra
```

The committed tests capture the profile in
`reconforge.benchmark.outbox_recovery.measure_bounded_recovery`; the benchmark
database remains disposable and synthetic.
