# ADR 0549: Fail closed when a bounded policy lacks an exact amount

- **Status:** Accepted
- **Date:** 2026-08-23
- **Execution slice:** E-835

## Context

`CentralPolicyEngine` already supported exact `Decimal` amount floors and ceilings. Before this slice, the comparisons ran only when `amount` was present. A caller could therefore supply a bounded policy (`minimum_amount` or `maximum_amount`) without the financial amount being authorized, and receive an otherwise-allowed decision.

## Decision

When either amount bound is present, the policy engine requires a finite exact `Decimal` amount. If it is absent, evaluation returns `amount_missing_for_bounded_policy` and denies access. Existing below-floor, above-ceiling, and in-range decisions remain unchanged. The rule applies equally through `evaluate` and `evaluate_any`.

## Rationale

This preserves deny-by-default ABAC semantics and prevents a missing financial attribute from bypassing an amount constraint. It does not invent a zero value, round an unknown value, or infer an amount from another field.

## Compatibility and rollback

The change is additive to the reason-code vocabulary. Callers that configure an amount bound must now provide `amount`; callers without bounds are unchanged. Rollback is a source-version rollback only; no database migration or data rewrite is required.

## Evidence and limits

`tests/test_policy_engine.py` covers missing lower-only, upper-only, and combined bounds plus existing exact boundary cases. This proves the local policy primitive, not universal adoption by every route, distributed policy cache invalidation, or production IAM effectiveness.
