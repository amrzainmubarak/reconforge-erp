# ADR 0755: Strict PostgreSQL financial hydration

- Status: Accepted
- Date: 2026-08-28
- Decision owners: ReconForge execution stream

## Context

Two PostgreSQL read boundaries converted database-returned values with
`Decimal(str(value))`: policy-analysis scope amounts and trial-balance debit and
credit totals. PostgreSQL numeric drivers normally return `Decimal`, but a
driver adapter, test double, or future result path returning a binary `float`
could cross these boundaries and be treated as exact. The first value affects
authorization analysis; the second affects financial balance evidence.

## Decision

Use `parse_exact_amount()` when hydrating policy scope amount bounds and trial-
balance totals. Reject binary floating-point, malformed, non-finite, and
negative values at the repository boundary, while preserving valid exact text,
integer, and Decimal values. A missing trial-balance aggregate remains the
existing explicit zero fallback; a present invalid value is never silently
converted to zero.

## Consequences

- Policy conflict analysis cannot digest an imprecise financial bound.
- Trial-balance evidence cannot derive minor-unit totals from a binary float.
- This is repository hydration and local input-integrity evidence; it does not
  establish PostgreSQL driver certification, external IAM, statutory posting,
  provider behavior, or production financial assurance.
- Existing valid PostgreSQL numeric responses retain their behavior.

## Verification

- `tests/test_postgres_policy_analysis.py::test_postgres_policy_scope_amount_rejects_binary_float`
- `tests/test_postgres_ledger.py::test_trial_balance_rejects_binary_float_totals_from_adapter`
- Existing PostgreSQL policy-analysis, ledger, trial-balance, scope, and audit
  tests
- Full regression and release gates recorded in `docs/execution/EVIDENCE.md`

