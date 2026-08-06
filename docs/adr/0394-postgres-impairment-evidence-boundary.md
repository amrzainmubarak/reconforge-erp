# ADR 0394: PostgreSQL impairment evidence is immutable and non-posting

## Context

ADR 0393 introduced a deterministic, read-only consolidation impairment bridge.
Without a server-profile persistence boundary, a team could calculate the
artifact locally but could not retain it under the same tenant, maker-checker,
audit, and replay controls as the other consolidation evidence artifacts.

## Decision

Add Alembic migration `0066_pg_impairment` and
`PostgresConsolidationImpairmentRepository`. The adapter:

- stores canonical request/result JSONB under forced tenant RLS;
- recomputes request/result digests before insertion and replay-verifies reads;
- makes retries idempotent by tenant/result digest;
- requires preparer/approver identities that are distinct and present in the
  tenant identity table;
- emits an audit event on creation; and
- rejects updates, deletes, and any result whose `posted` flag is true.

The adapter does not choose a cash-generating-unit boundary, valuation method,
discount rate, tax treatment, statutory recognition, journal posting, or source
system write-back. The live test is capability-gated by
`RECONFORGE_TEST_POSTGRES_DSN`; a skipped live test is not promoted to a pass.

## Evidence

- `tests/test_postgres_consolidation_impairment.py` covers the SQL and linear
  migration contract.
- `tests/test_postgres_consolidation_impairment_runtime.py` exercises idempotent
  replay, tenant isolation, replay verification, and append-only triggers when
  a disposable PostgreSQL service is configured.
- `docs/execution/POSTGRES_PARITY_INVENTORY.yaml` records the adapter as
  `contract_only` until an unskipped runtime result is available.

## Consequences

The impairment bridge now has a governed PostgreSQL evidence home, but it is
still a bounded experimental non-posting artifact and does not close the
financial consolidation, statutory accounting, or production-readiness gates.
