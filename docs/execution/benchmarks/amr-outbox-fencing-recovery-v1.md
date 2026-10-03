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

The local Python 3.14.6 profile ran against a temporary SQLite file after the
fencing schema constant was applied:

```text
backend=sqlite events=1000 batch_limit=100 calls=11 recovered=1000
largest_batch=100 recovery_wall_seconds=0.022337
```

`EXPLAIN QUERY PLAN` reported:

```text
SEARCH outbox_events USING INDEX idx_outbox_expired_lease (locked_at>? AND locked_at<?)
```

The focused SQLite recovery/race/evidence and continuity suite completed 31
tests successfully.  The profile does not measure cross-process publisher
latency, storage durability beyond SQLite's selected local settings, or a
general capacity limit.

## PostgreSQL evidence

A disposable Docker PostgreSQL 17 Alpine instance used a separate
non-superuser/non-`BYPASSRLS` `reconforge_app` role.  It was migrated to the
current `0100_pg_inventory_receipt` target, then received
`POSTGRES_OUTBOX_FENCING_SCHEMA_SQL` directly for this bounded pre-migration
integration test.

```text
backend=postgresql events=1000 batch_limit=100 calls=11 recovered=1000
largest_batch=100 recovery_wall_seconds=0.676690
```

The recovery candidate plan selected `idx_outbox_expired_lease` with an index
condition on the tenant and expired claim timestamp.  The live suite passed 11
tests, including same-label stale acknowledgement refusal, final-attempt
recovery, `SKIP LOCKED` ownership, RLS isolation, trigger rollback, immutable
evidence, populated upgrade marking, and this profile.

These measurements apply only to this synthetic single-node environment.  They
are not a broker benchmark, external delivery result, HA/DR test, capacity
claim, or production service objective.

## Reproduction

Run the focused suites only after applying the migration integration required by
ADR 0827.  The PostgreSQL variables must point at a disposable server with a
separate application role.

```powershell
python -m pytest tests/test_outbox_fencing_recovery.py tests/test_outbox_evidence_continuity.py -q -ra

$env:RECONFORGE_TEST_POSTGRES_ADMIN_DSN='postgresql://postgres:***@127.0.0.1:5432/postgres'
$env:RECONFORGE_TEST_POSTGRES_DSN='postgresql://reconforge_app:***@127.0.0.1:5432/postgres'
$env:RECONFORGE_TEST_POSTGRES_APP_USER='reconforge_app'
python -m pytest tests/test_postgres_outbox_fencing_recovery.py -q -ra
```

The committed tests capture the profile in
`reconforge.benchmark.outbox_recovery.measure_bounded_recovery`; the database
setup is intentionally test-local until the required migration/backup slice is
merged.
