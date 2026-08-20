# ADR 0529: Policy-bearing artifact constructors fail closed

- **Date**: 2026-08-12
- **Status**: Accepted

## Context

E-718 validated policy metadata for several frozen matching/result artifacts, and
E-717 validated Work-order result construction. Other policy-bearing artifacts
that are still public constructors (`VarianceThresholdPolicy`, `ClientPackOptions`,
and `RulePackExecution`) trusted type annotations only, so unsupported policy
strings could still be observed by downstream artifact/report/strategy consumers
through direct construction.

## Decision

Validate and normalize `financial_input_policy` inside `__post_init__` for each
listed frozen artifact constructor using the same canonical policy validation used
by core monetary ingress paths. Unsupported policy values raise
`InvalidAmountError` at construction time; strict-v2 remains the default and
legacy-v1 remains explicit compatibility only.

## Verification

`tests/test_variance_analysis.py`, `tests/test_client_pack_financial_input_policy.py`,
and `tests/test_rules_engine.py` reject unsupported constructor policy values, while
Ruff and Mypy pass. Existing full local regression and release/security gates from
E-718 remain the same baseline.

## Rollback

Revert the constructor validators, focused tests, and this ADR together.
