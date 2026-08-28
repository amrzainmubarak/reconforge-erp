# ADR 0556: Bind reconciliation run submission to amount-bounded ABAC

- Status: Accepted
- Date: 2026-08-23
- Scope: PostgreSQL server-only reconciliation run submission

## Context

The run submission already validated and registered canonical inputs containing
amounts, but authorization received no amount context. A bounded central policy
therefore could not distinguish a small run from a large one.

## Decision

Before server scope authorization, parse every non-null input amount with the
exact Decimal parser and compute the gross absolute sum. Pass this amount to
the central policy. If any input amount is absent, pass `None`; this allows
non-amount matching runs under unbounded policies while guaranteeing that a
bounded policy fails closed rather than inferring zero. Invalid finite input is
rejected with a safe API error before persistence.

## Consequences and evidence

The change is additive and has no schema or migration impact. The synthetic
two-record submission binds `Decimal("20.00")`; focused API tests pass 2/2 and
Ruff/Mypy pass. A full pre-slice regression completed with exit code 0 over
3,119 collected tests. Live PostgreSQL, durable worker propagation, provider
execution, posting, and production IAM remain outside this ADR.

Rollback is a source revert, which removes amount context from run submission.
