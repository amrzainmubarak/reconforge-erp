# ADR0867: Order AR currency-binding admission before business locks

- Status: Accepted
- Date: 2026-10-18

## Witness

Completing the skipped live baseline on a migrated, explicitly provisioned
ordinary AR role exposes three SQLSTATE40P01 deadlocks. A customer upsert holds
the existing workspace currency-binding advisory lock and waits for a customer
row; concurrent invoice/receipt creation holds that customer and waits for the
binding. Concurrent first upserts followed by invoice creation produce the same
cycle. The original native result retains all three failures.

## Decision

Use the existing `FinancePolicyStore.lock_binding` before command/customer locks
in invoice creation and receipt posting. Invoice approval and receipt allocation
take the same admission immediately after their existing document read, before
locking its customer. Customer upsert already uses this order through capture.
The lock key remains tenant/workspace scoped. Capture still verifies the current
binding and the original monetary policy; authorization, currency affinity,
credit exposure, expected versions, idempotency and journal values are unchanged.
Do not catch/retry deadlocks, increase deadlines or weaken the allowed outcomes.

The shared AR test fixture now owns a fresh ordinary login and provisions its
existing finite AR/audit profile and read-only owner dependencies. It no longer
depends on another file's grants. Both full integrity files run in mandatory CI;
the original three concurrency regressions remain intact.

## Evidence and rollback

After profile provisioning, the first actual run passes31 cases and fails the
three concurrency cases above. The repaired run passes all34 selected PostgreSQL
cases with zero skips in55.328s wall. The existing SQLite contract and complete
successor CI remain required; no throughput claim follows from this diagnostic.
See `FULL_REGRESSION_2026-10-18.md` for the retained evidence paths.

There is no schema/data migration or public contract change. Reverting the four
admission calls restores the previous lock order and its witnessed deadlock.
