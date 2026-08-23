# ADR 0555: Bind ownership-change preparation to amount-bounded ABAC

- Status: Accepted
- Date: 2026-08-23
- Scope: PostgreSQL server-only consolidation ownership-change preparation

## Context

The prepare route re-evaluated server permissions without an amount, leaving a
bounded central policy unable to evaluate the transaction exposure.

## Decision

Convert the request to typed domain values before authorization. Pass the exact
gross exposure

`abs(net_assets * (prior_group_ownership - new_group_ownership)) + abs(consideration_effect)`

as a `Decimal` to central policy before persistence. Derived parent-equity
effects are not counted again. Read routes remain amount-free.

## Consequences and evidence

This additive source change has no schema or migration impact. The synthetic
fixture exposure is exactly `Decimal("220.00")`; focused route/domain/dependency
tests pass 19/19 with the live PostgreSQL case explicitly skipped when no
service is configured. Universal route adoption, provider behavior, posting,
and production IAM effectiveness remain outside this decision.

Rollback is a source revert, which would regress amount context for bounded
policy evaluation.
