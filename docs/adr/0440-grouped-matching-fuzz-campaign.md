# ADR 0440: Bounded property/fuzz campaign for grouped matching

- Status: accepted
- Date: 2026-08-07
- Scope: `P4-MAT-001`, `grouped_matching.correctness`

## Decision

Add a deterministic Hypothesis campaign around the public grouped-matching
domain boundary. Generated records vary amount, fee, currency, partition, and
business date while keeping identities unique and budgets finite. The campaign
checks permutation-stable decisions/digests, closed currency/partition/date
selection, fail-closed search-budget refusal, portfolio non-overlap, and
portfolio replay digest stability.

## Evidence boundary

The campaign is synthetic, bounded, and runs in-process. It strengthens
property/fuzz coverage but does not establish a source-code mutation score,
PostgreSQL engine parity, distributed queue fault coverage, live-rate validity,
or production performance/capacity.

## Rollback

Remove `tests/test_grouped_matching_fuzz.py`, this ADR, its manifest entry, and
the E-594 execution records. Existing grouped strategy and replay contracts
remain unchanged.
