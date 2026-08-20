# ADR 0381: Dense grouped-matching adversarial contracts

- **Status**: Accepted
- **Date**: 2026-08-06
- **Scope**: Experimental, bounded, non-posting grouped matching

## Context

The grouped matcher already supports fee-aware netting, FX conversion, partial
settlement, explicit ambiguity, and deterministic search budgets. The existing
contracts exercised these capabilities mostly in isolation. Dense combinations
can fail in more dangerous ways: selecting one of several equal optima,
silently accepting a cross-partition/currency candidate, or returning a partial
selection after a budget ceiling.

## Decision

Keep the domain and application APIs unchanged and add a focused adversarial
contract suite. The suite combines:

1. fee-aware netting with several equal-cost many-to-many candidates;
2. fee-aware FX conversion with permutation replay;
3. dense candidate generation over a deliberately small search budget; and
4. mixed partition/currency candidates that must remain unmatched.

Each case requires either an exact deterministic decision or an explicit
fail-closed ambiguity/unmatched result. No test treats a stable tie-break as
financial approval, and no case posts or writes back.

## Consequences

- Equal-cost alternatives remain visible through `GROUP_MATCH_AMBIGUOUS` and
  candidate sets.
- FX and fee totals are asserted after canonical conversion, including replay
  digest stability under record permutation.
- Budget refusal is checked for empty selected identities and stable digests.
- The suite is a bounded correctness contract, not a performance, fuzzing,
  mutation-score, PostgreSQL parity, live-rate, or production claim.

## Verification and rollback

`tests/test_grouped_matching_adversarial.py` passes four focused cases under
the locked environment, Ruff and Mypy pass, and the test is included in the
source distribution. Removing the test and this ADR is fully reversible; no
schema, migration, or persisted-data change is involved.
