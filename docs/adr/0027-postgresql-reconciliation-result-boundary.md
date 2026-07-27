# ADR 0027: Tenant-scoped PostgreSQL reconciliation result boundary

## Status

Accepted — bounded persistence capability.

## Context

The deterministic local matcher now generates ordered, explainable matches and
retains unmatched records on both sides. Hosted PostgreSQL persistence still
needed a financial record contract that could prove no registered input was
silently discarded and that a result was not reused beyond its configured
cardinality.

## Decision

Add PostgreSQL migration `0009_postgres_reconciliation_results` with:

- `reconciliation_runs` for algorithm/rule/input metadata, lifecycle state, and
  completion hashes.
- `reconciliation_inputs` for canonical left/right source manifests,
  original-vs-normalized reference values, strict decimal amounts, validity,
  and explicit allowed-use counts.
- `reconciliation_results` for matched, unmatched, invalid, ambiguous,
  duplicate, and policy-rejected results with stable identifiers, confidence,
  explanations, reason codes, lineage JSON, and exact amount differences.
- `reconciliation_exceptions` for independently classified, risk-scored,
  workflow-visible exception evidence.

The repository requires every registered input to appear in at least one result
before a run can become `Complete`. It also rejects any source record whose
result-use count exceeds `allowed_uses`. Completion calculates deterministic
input-manifest and result-set hashes and appends audit/outbox events in the
caller transaction.

Database triggers prevent mutation of completed children and deletion of runs.
Forced RLS applies to all four tables. The boundary persists matcher output; it
does not claim that candidate generation, global assignment, or large-dataset
execution has moved into PostgreSQL.

## Consequences

Positive:

- Hosted reviewers can reproduce what inputs and results were persisted.
- Invalid/unmatched/ambiguous results remain first-class records rather than
  disappearing from a run.
- Stable IDs derive from tenant/run/source business keys, not row order.
- Completion state is protected by database and repository invariants.

Remaining work:

- Harden and operate the explicit canonical-record adapter through the hosted
  worker contract; its current schema-only in-memory SQLite dependency must not
  become a hosted persistence path.
- Add hosted search/filtering and UI result investigation routes.
- Add streamed candidate pruning and global assignment over relation-native
  inputs for large datasets. The explicit hard-key partition path now has
  tenant-scoped PostgreSQL server-cursor input streaming and idempotent output
  checkpoints, but this does not claim global relation execution or cross-engine
  parity at million-row scale.

## Validation

- Contract and invariant tests: `tests/test_postgres_reconciliation.py`.
- Migration-chain checks: `tests/test_alembic_postgres.py`.
- Optional live non-privileged RLS test:
  `test_live_postgres_reconciliation_persists_complete_runs_under_rls`.
