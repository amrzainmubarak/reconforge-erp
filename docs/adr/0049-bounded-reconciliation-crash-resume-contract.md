# ADR 0049: Bounded Reconciliation Crash/Resume Contract

- Status: Accepted — bounded verification only
- Date: 2026-07-25
- Scope: PostgreSQL reconciliation worker lease/checkpoint control flow

## Context

The reconciliation worker already commits each hard-key partition and its
output hash in a separate transaction, stores an immutable checkpoint, and
allows a new worker to claim a `Running` execution after its lease expires.
The existing regression covered a managed matcher exception: the worker wrote
`Failed`, an operator explicitly requeued the run, and the retry skipped the
committed checkpoint. That is useful retry evidence but does not exercise the
state left by abrupt process termination.

This local environment has no live PostgreSQL service. A bounded contract test
can verify the worker control flow and exact SQL predicate without claiming an
operating-system kill, database durability, or production recovery exercise.

## Decision

1. Model abrupt termination with a test-only `BaseException` raised immediately
   after the worker has returned from the transaction that commits the first
   partition. The worker deliberately catches `Exception`, not
   `BaseException`, so this termination is not converted into a managed
   `Failed` state.
2. Preserve the resulting `Running` state, first worker ID, execution attempt,
   committed output, and checkpoint. A replacement worker must receive
   `PostgresReconciliationBusyError` while the lease is active.
3. Advance only the deterministic repository test clock to expire the lease.
   The replacement worker then claims the same run as execution attempt two,
   reads the completed checkpoint keys, and processes only the remaining
   partition.
4. Bind the test double to the production claim query by requiring its
   `execution_status = 'Queued'` and
   `execution_lease_until <= now()` predicates. Do not implement a parallel
   in-memory claim rule that could pass while production SQL regresses.
5. Compare the resumed run with an uninterrupted run using the same synthetic
   inputs and run identifier. Input-manifest hash, result-set hash, and the
   complete multiset of partition output hashes must match; result IDs and
   checkpoint keys must remain unique, and each partition may be yielded in
   only one execution attempt.
6. Keep `P1-PLAT-004` planned. Its broader exit requires a real process/service
   restart against a supported live database and operational recovery evidence.

## Consequences

- The bounded worker contract now distinguishes managed failure/requeue from an
  unhandled termination followed by lease-based takeover.
- A worker cannot steal an active lease in the test contract, and takeover does
  not duplicate committed financial output.
- Runtime code and database schemas are unchanged; this slice verifies behavior
  that was already implemented by the worker, repository, and migration.
- The evidence does not verify PostgreSQL transaction durability, clock skew,
  connection loss during commit, pod/process supervision, supported-version
  matrices, or recovery time objectives. The existing live PostgreSQL test
  remains skipped when its explicitly configured service is unavailable.

## Rollback

The test and documentation can be removed without a runtime migration, but that
would reopen the abrupt-termination evidence gap. Do not replace the test with
the managed `Failed`/requeue case, bypass the pre-expiry busy assertion, or
compare only output counts. A future live crash test should extend this bounded
contract and retain its exact hash and no-duplicate assertions.
