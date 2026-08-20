# ADR 0217: Bounded non-overlapping grouped portfolio

## Context

The grouped matcher previously returned one bounded group.  Real reconciliation
partitions can contain several independent settlements, but repeatedly calling
the single-group matcher would make the result depend on greedy order and could
reuse records.

## Decision

1. Add `portfolio` mode alongside the existing grouped modes without changing
   the single-decision compatibility API.
2. Enumerate exact candidate groups under the existing currency, partition,
   date, cardinality, and search ceilings. Select a non-overlapping set by
   maximum covered records, then minimum aggregate exact difference.
3. Return each selected group as an explainable decision plus explicit
   unmatched IDs. If candidate generation or selection exceeds the budget, or
   equal maximum-cover portfolios exist, return one unresolved ambiguity and
   never choose a greedy fallback.
4. Expose the mode through the backend-neutral application service, strategy
   manifest, Reconciliation-as-Code model, and published schema/document.

## Consequences

ReconForge can now prove several disjoint exact groups in one bounded run with
permutation-stable portfolio digests.  This does not implement partial groups
inside the portfolio, carry-forward/sequence/reversal-specific matching,
mutation/crash-resume or cross-engine properties, or large benchmark claims.

## Rollback

Remove portfolio mode, the application/strategy wiring, tests, manifest/schema
entries, ADR, and execution records.  No migration, external call, posting,
write-back, release, or deployment rollback is required.
