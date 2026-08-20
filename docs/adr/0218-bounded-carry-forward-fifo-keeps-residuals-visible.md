# ADR 0218: Bounded carry-forward uses governed FIFO and visible residuals

- Status: accepted
- Date: 2026-08-02

## Decision

Add a persistence-independent `bounded-carry-forward-fifo` strategy for one currency and partition at a time. Settlements are allocated to the oldest eligible obligations inside a declared date window using exact `Decimal` amounts. Every allocation records both residual balances and a stable sequence rank. Candidate evaluation and allocation counts are bounded; exhaustion returns `ambiguous` with remaining IDs rather than silently stopping.

## Consequences

The strategy provides deterministic sequence/window evidence without posting, write-back, reversal pairing, crash resume, or cross-engine parity. Negative amounts, multi-currency conversion, and cross-partition allocation remain outside this contract. Residuals stay actionable for a later run or human review.

## Rollback

Remove the carry-forward domain/strategy files, tests, ADR, manifest entry, and execution records. No database, source-system, hosted-service, release, or production state is mutated.
