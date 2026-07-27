# ADR 0029: Bounded reconciliation partitioning and multi-worker scheduling

## Status

Accepted — bounded scale foundation.

## Context

The hosted reconciliation worker must preserve deterministic global assignment
and financial lineage while avoiding an unbounded candidate graph. A generic
chunk split is unsafe: records that can match across chunks would silently
become unmatched. Worker slots also need durable ownership so two processes
cannot persist the same run concurrently.

## Decision

Support opt-in hard-key partitioning in `LocalDeterministicMatcherAdapter`:

- `rule.partition_fields` identifies canonical fields that are a hard policy
  boundary; candidates are never considered across different partition keys.
- `rule.partition_max_records` bounds the combined left/right records in each
  partition and fails closed when a partition is too large.
- Partitions are processed in stable hash order, with cancellation checks and
  bounded progress heartbeats. Results remain explainable and include the
  applied partition fields in result lineage.
- The default with no partition fields remains the existing global assignment
  path; partitioning is never inferred silently.

`PostgresReconciliationScheduler` runs a configured set of worker IDs in
bounded concurrent slots. PostgreSQL claim leases, worker ownership, and
completion invariants remain the source of truth; the scheduler does not use
an in-memory lock as a substitute for database coordination.

## Consequences

Positive:

- Large, well-partitioned reconciliation graphs can be bounded without changing
  the deterministic matching algorithm within a partition.
- Reordering inputs or scheduler slots does not change partition output.
- Lease ownership and retry semantics remain centralized in PostgreSQL.
- Cancellation and progress remain visible while partitions are processed.

Limitations:

- Partition fields are hard constraints and must be selected by the caller;
  incorrect fields can create legitimate unmatched records.
- Revision `0011_postgres_reconciliation_checkpoints` adds tenant-scoped,
  idempotent output checkpoints. Partition-capable workers commit a partition's
  results, exceptions, and deterministic output hash atomically, and explicit
  requeue skips committed partitions after a failure. The worker now streams
  partition inputs from PostgreSQL; global relation-native assignment and
  million-row benchmark evidence remain outside this ADR.

## Validation

- `tests/test_postgres_reconciliation.py` covers partition row-order
  invariance, progress, fail-closed partition limits, scheduler aggregation,
  managed retry, and the ADR 0049 bounded unhandled-termination/lease-takeover
  contract with exact resumed/uninterrupted hash equality and no duplicate
  business effect.
- Full matching, worker, migration, API, and repository suites remain required
  before publishing scale claims.
