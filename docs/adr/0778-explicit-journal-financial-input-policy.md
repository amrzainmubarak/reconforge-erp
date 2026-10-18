# ADR 0778: Name the financial input policy in Journal Controls

- Status: Accepted
- Date: 2026-08-29
- Owners: Financial Integrity / Journal Controls

## Context

Journal Controls parse a high-value threshold and persisted journal amounts.
The shared parser already defaulted to strict financial input, but the domain
function signatures and the SQLite/PostgreSQL adapter calls did not carry that
policy explicitly. This made the call graph less auditable and left the
compatibility boundary implicit.

## Decision

Add a named `FinancialInputPolicy` argument to `journal_threshold()` and
`evaluate_journal_policies()`, defaulting to the current strict policy for
backward-compatible direct callers. Pass `STRICT_FINANCIAL_INPUT_POLICY`
explicitly from the SQLite and PostgreSQL production adapters. Legacy float
behavior remains available only when a domain caller explicitly selects the
legacy policy, and it remains warning-bound.

No database schema or migration changes are needed: this slice controls the
parsing decision before journal exceptions are created and does not claim that
the existing journal path posts statutory books.

## Consequences and rollback

The reviewed production call graph now makes the financial input policy visible
and fail-closed for binary floating-point values. Compatibility callers can
continue during the deprecation window without silently changing the current
strict production behavior. Rollback is a source/test/ADR/execution-record
revert with no external state mutation.
