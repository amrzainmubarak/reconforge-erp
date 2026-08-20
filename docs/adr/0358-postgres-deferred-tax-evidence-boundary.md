# ADR 0358: Persist acquisition deferred-tax evidence without posting

## Status

Accepted for the bounded finance foundation.

## Context

The deterministic acquisition deferred-tax bridge was previously available as a
local calculation and replayable JSON artifact only.  A team deployment needs
tenant-isolated persistence and authenticated retrieval, but the current
product positioning does not support statutory tax recognition, legal-book
posting, tax-law interpretation, valuation allowances, or source-system
write-back.

## Decision

- Add PostgreSQL migration `0065_pg_deferred_tax` with a forced
  tenant-RLS table and an append-only trigger.
- Store canonical request/result JSON, request/result digests, maker-checker
  actors, acquisition identity, and approval time.
- Recompute the deterministic bridge before insert, reject posted results, and
  replay-verify both request and result digests on read.
- Make retries idempotent by tenant and result digest; conflicting immutable
  identities fail closed.
- Expose only a PostgreSQL server-profile API.  POST requires
  `finance_core.manage`; GET requires `finance_core.read` or
  `finance_core.manage`, with central tenant policy re-evaluation and no
  synthetic workspace.
- Keep the artifact explicitly non-posting.  Any statutory recognition or
  journal effect requires a separate reviewed close workflow and ADR.

## Consequences

This closes the persistence/API parity gap for the declared deterministic
bridge while preserving the claim boundary.  It does not establish tax-law
correctness, statutory financial statements, deferred-tax accounting policy,
live rates, ERP/bank integration, write-back, HA/DR, or production readiness.

## Verification

- `tests/test_postgres_consolidation_deferred_tax.py`
- `tests/test_postgres_consolidation_deferred_tax_runtime.py` when a disposable
  PostgreSQL service is configured
- `tests/test_api_consolidation_deferred_tax.py`
- full local pytest, Ruff, Mypy, Bandit, pip-audit, build, and diff-check gates
