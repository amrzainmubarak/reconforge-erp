# ADR-0522: Reviewed per-run budgets for grouped matching

## Status

Accepted — additive request-level ceilings; distributed parity, mutation
coverage across every backend, and production sizing remain open.

## Context

The grouped matcher already had bounded manifest ceilings, but callers could
only accept the single default budget. A dense reconciliation may need a
smaller, explicitly reviewable search budget to fail closed earlier without
silently changing the algorithm or allowing an unreviewed ceiling increase.

## Decision

Add an optional `GroupedMatchBudget` to `MatchingStrategyRequest`. It may lower
the published grouped strategy's left/right cardinality and search-evaluation
ceilings. The request is rejected when a value exceeds the manifest, violates
the mode's cardinality floor, or is supplied to a non-grouped strategy. The
selected budget is included in the canonical input digest; the grouped
decision digest already records the effective policy, so replay can prove the
applied limits.

## Verification and boundary

`tests/test_matching_strategy_contract.py` covers lower-budget behavior,
digest binding, ceiling/floor refusal, and non-grouped non-silent rejection.
Ruff, Mypy, and the full local regression are required for E-712. This does
not claim a domain-wide mutation score, live-backend replay parity, distributed
fault injection, throughput, or production sizing.

## Rollback

Revert the request contract, adapters, tests, docs, and E-712 records together;
the strategy manifest identity and persisted schemas remain unchanged.
