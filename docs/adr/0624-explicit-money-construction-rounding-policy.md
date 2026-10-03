# ADR 0624: Make every production Money construction choose its precision policy

- Status: Accepted
- Date: 2026-08-25
- Decision owners: Financial Controls, Domain Engineering, QA
- Scope: `Money.from_exact` call sites under `reconforge/`

## Context

`Money.from_exact` uses the installed currency registry's rounding policy when
`strict_precision` is omitted. That default is useful for compatibility, but
an omitted keyword at a production call site hides whether the value is an
external amount that must be rejected when over-precise or a derived result
that is intentionally rounded. The ambiguity is especially risky in domain
calculations that later become reconciliation or control evidence.

An AST audit found production call sites without an explicit precision choice.
The fix must preserve the existing derived-calculation behavior while making
source-ingress and rounding decisions reviewable and regression-testable.

## Decision

1. Every production `Money.from_exact` call must pass a literal boolean
   `strict_precision` argument. The repository test suite rejects a missing or
   non-literal policy.
2. Domain source-value helpers in manufacturing and retail use
   `strict_precision=True`, so an amount with more fractional digits than the
   registered currency policy fails closed instead of being silently rounded.
3. Derived deferred-tax, non-controlling-interest, and ownership-change
   calculations use `strict_precision=False` explicitly. This preserves the
   registry's declared rounding policy and keeps the resulting rounding delta
   visible where the domain already records one.
4. Zero initializers and other exact canonical values use
   `strict_precision=True`. No public API, CLI, schema, artifact version, or
   compatibility reader changes in this slice.

## Consequences and boundaries

- A future production call site cannot silently inherit the constructor's
  default rounding behavior.
- Registered currency precision and the registry's `ROUND_HALF_UP` policy
  remain the source of truth for intentional derived rounding.
- The change improves the `Money.from_exact` boundary only. It does not prove
  that every financial path uses `Money`, that source files are authentic, or
  that posting, providers, write-back, PostgreSQL parity, HA/DR, or production
  operations are complete.

## Compatibility and rollback

The derived calls retain their previous effective `strict_precision=False`
behavior; source-helper calls now reject inputs that were previously rounded.
Rollback is limited to the explicit call-site keywords, the AST regression,
this ADR, and execution records. Do not remove the test while retaining an
implicit financial rounding boundary.

## Verification

- The focused domain/control collection contains 67 tests and passes.
- `tests/test_p0_correctness.py::test_production_money_construction_declares_rounding_policy`
  finds no production `Money.from_exact` call without a literal boolean policy.
- Ruff, Mypy, and `git diff --check` pass for the changed scope.
