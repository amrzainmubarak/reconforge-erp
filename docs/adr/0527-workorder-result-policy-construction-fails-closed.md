# ADR 0527: Work-order result policy metadata fails closed at construction

- **Date**: 2026-08-11
- **Status**: Accepted

## Context

E-715 bound the selected financial-input policy to every Work-order monetary
ingress and made combined management packs reject mixed policies. A manually
constructed `WorkorderReconciliationResult` could still carry an unsupported
runtime string because the type annotation alone is not runtime validation.

## Decision

Validate and normalize `financial_input_policy` in the frozen result's
`__post_init__` before the result can be returned to a caller. Unsupported
values raise the existing `InvalidAmountError` without parsing any financial
value or creating an artifact. Explicit legacy-v1 remains representable for
named historical compatibility, while the default remains strict-v2.

## Verification

`tests/test_workorder_reconciliation.py` proves unsupported result metadata is
rejected. The focused Work-order/report/CLI/reconciliation-policy suite passes
47 tests; Ruff and Mypy pass. The existing full local regression and package
gates from E-715 remain the compatibility baseline. No schema, migration,
provider, posting, write-back, or publication behavior changes.

## Rollback

Revert the result validator, regression test, ADR, manifest, and E-717 records
together. Existing strict/legacy policy semantics and persisted artifacts are
unchanged.
