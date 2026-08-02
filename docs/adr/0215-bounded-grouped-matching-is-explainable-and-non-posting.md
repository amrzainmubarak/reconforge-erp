# ADR 0215: Bounded grouped matching is explainable and non-posting

## Context

The existing deterministic pair matcher supports capacity-constrained edges,
but the Phase 4 advanced-matching objective also needs genuine grouped and
netting decisions.  Unbounded subset search would make a financial decision
depend on memory, timing, or an accidental greedy order.

## Decision

1. Add a persistence-independent `grouped_matching` contract with exact
   `Decimal` amounts, explicit currency, optional sourced FX conversion, and
   signed fee adjustments.
2. Enumerate both-side subsets only up to a declared group size and candidate
   budget.  Select non-overlapping groups by maximum covered record count,
   then minimum exact difference, with stable record-ID ordering.
3. Return `matched`, `unmatched`, or `ambiguous` decisions.  Equal optimum
   groupings and exhausted search budgets remain explicit ambiguity; they are
   never resolved by a hidden tie-break.
4. Keep the slice pure and non-posting.  It does not mutate a ledger, call a
   connector, allocate a partial settlement, or claim a performance tier.

## Consequences

ReconForge now has tested one-to-many, many-to-one, and true bounded
many-to-many/netting evidence with permutation-stable digests, fee/FX lineage,
and visible limits.  Partial settlement allocation, carry-forward, sequence
matching, mutation testing, crash/resume integration, and 10K/100K/1M
benchmarks remain separate work in `P4-MAT-001`.

## Rollback

Remove the grouped matcher, focused tests, manifest entry, ADR, and execution
records.  No migration, source-system mutation, connector call, tag, release,
or deployment rollback is required.
