# ADR 0751: Bound PostgreSQL input partition materialization

- Status: Accepted
- Date: 2026-08-28
- Decision owners: ReconForge execution stream

## Context

The PostgreSQL reconciliation repository already read inputs through a
server-side cursor and the worker rejected an oversized partition after the
partition had been delivered. The repository nevertheless accumulated every
row in the current hard-key partition first. A dense or malicious partition
could therefore consume excessive Python memory before the existing safety
check ran.

## Decision

`PostgresReconciliationRepository.iter_input_partitions()` accepts a validated
`max_partition_records` ceiling, defaults it to the existing 10,000-record
worker limit, and checks the current partition size before appending another
row. It raises a `PostgresReconciliationIntegrityError` when the next row
would exceed the ceiling. The PostgreSQL worker derives the persisted
`partition_max_records` value through the same validation helper used by local
partition execution, and passes it to the repository. The repository clamps
each cursor fetch batch to that ceiling, so direct repository callers receive
the same bound as the worker path.

The behavior is fail-closed: it does not truncate the partition, emit a
partial match, or pass an oversized partition to a matcher. The limit is a
per-hard-partition materialization control and is not a claim about database
memory isolation, total-run capacity, or production sizing.

## Consequences

- PostgreSQL input materialization has an explicit boundary before matching.
- A partition whose hard key is too coarse produces a retryable worker failure
  with a refinement instruction rather than an unexplained partial result.
- Existing callers retain the historical 10,000-record default and may lower
  the limit explicitly.
- The cursor batch is bounded, but the database driver and PostgreSQL server
  remain separate resource domains requiring their own operational evidence.

## Verification

- `tests/test_postgres_reconciliation.py::test_postgres_input_partition_limit_is_enforced_during_cursor_accumulation`
- `python -m pytest -q tests/test_postgres_reconciliation.py --tb=short`
- Full regression and release gates recorded in `docs/execution/EVIDENCE.md`.
