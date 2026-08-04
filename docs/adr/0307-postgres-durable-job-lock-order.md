# ADR 0307: Keep PostgreSQL durable-job locks in aggregate order

- Status: accepted
- Date: 2026-08-04
- Scope: PostgreSQL durable-job claim, checkpoint, and completion transactions

## Context

`claim_next` locks the durable-job aggregate row before re-reading its lease
row. The owned-transition paths previously locked the lease row first and
then updated the aggregate row. During same-tenant contention, a worker
reclaiming an expired job could therefore hold the aggregate row while the
current owner held the lease row, producing a PostgreSQL deadlock.

The failure was observed in the live server-boundary contract as
`psycopg.errors.DeadlockDetected` while two workers drained a synthetic queue.
The error was intermittent and did not indicate duplicate effects or an
authorization bypass, but an unhandled deadlock is still an availability bug
for the durable-job runtime.

## Decision

All owned-transition paths acquire the durable-job row with `FOR UPDATE` before
checking and locking the corresponding lease row. This makes the lock order
`durable_jobs -> durable_job_leases` consistent with `claim_next`. The
aggregate version check remains the authoritative stale-worker fence, and the
transaction still rolls back atomically on conflict.

## Verification

- The existing live PostgreSQL same-tenant contention contract passed 10/10
  repeated local runs after the change.
- The live PostgreSQL 10K-effect profile passed with 2,500 jobs and 10,000
  effects, with no duplicate effects or queued/running residue.
- Hosted CI must rerun the server-boundary job before this remediation is
  considered remotely verified.

## Boundary and rollback

This addresses one transaction lock-order deadlock only. It does not establish
queue HA, automatic failover, distributed fairness, soak, or production SLOs.
Rollback is limited to removing the `_lock_job` calls and this ADR; the schema,
lease generations, and public application contracts remain unchanged.
