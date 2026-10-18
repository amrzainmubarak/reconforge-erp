# ADR 0621: Enforce currency precision at application financial ingress

- Status: Accepted
- Date: 2026-08-25
- Scope: Local application readers that construct canonical `Money` from source exports or user-supplied tolerances

## Context

`Money.from_exact` already rejected binary floating-point input under strict
financial-input-v2, but its `strict_precision` option remained opt-in. A source
amount such as `100.001` for EUR could therefore be quantized to `100.00` by a
local application reader. That changes source meaning before reconciliation and
violates the platform invariant that over-precise or malformed financial input
becomes a visible data-quality exception.

Derived domain calculations are different: a tax, FX, consolidation, or other
calculated result may intentionally apply the registered rounding policy at its
bounded output boundary. This decision must not convert those calculation
boundaries into source-ingress rejection accidentally.

## Decision

All `Money.from_exact` calls in `reconforge/application/` must explicitly pass
`strict_precision=True`. The covered application boundaries are:

- bank statement and ledger records, including the amount tolerance;
- individual cashflow transactions and budgets;
- manufacturing standard/unit/actual costs and amount tolerance;
- professional invoices, payments, and amount tolerance;
- retail POS/processor monetary fields and settlement tolerance;
- grouped matching source amounts.

The legacy scalar `Money(...)` behavior and named legacy financial-input policy
remain available for existing compatibility readers. No schema, CLI, API, or
artifact version is changed by this slice. A repository AST regression test
prevents a future application-level `Money.from_exact` call from silently
omitting the precision decision.

## Evidence and acceptance

- `tests/test_bank_statement_control.py` proves that an EUR ledger amount with
  three fractional digits and an EUR tolerance with three fractional digits are
  rejected instead of rounded.
- `tests/test_p0_correctness.py` checks every application-level
  `Money.from_exact` call for an explicit `strict_precision=True` keyword.
- The existing Money compatibility tests continue to cover registered currency
  precision, strict rejection, legacy rounding, invalid values, and exact
  arithmetic.

## Security and financial correctness

The change fails closed on an input that cannot be represented at the declared
currency precision. It does not inspect or log the raw amount in the raised
application error. It does not authenticate source files, prove provider
authenticity, or enable posting/write-back.

## Compatibility and rollback

Valid source values and existing canonical output remain unchanged. Previously
accepted over-precise source values now fail at the application boundary rather
than being rounded; operators must correct the source or provide an explicitly
approved representation. Rollback is a reversible code change, but would
reintroduce silent source rounding and therefore requires a new decision and
regression evidence.

## Residual limitations

This closes application source-ingress precision for the listed local paths. It
does not prove every financial field in the repository is Decimal/minor-unit
backed, does not close PostgreSQL parity or hosted runtime gates, and does not
remove all named legacy compatibility readers.
