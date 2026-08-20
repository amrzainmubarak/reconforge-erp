# ADR 0219: Bounded reversal pairing is explicit and non-posting

- Status: accepted
- Date: 2026-08-02

## Decision

Add an experimental `bounded-reversal-pairing` strategy that pairs opposite-sign records within one currency/partition and a declared date window. An explicit `reversal_of` link outranks inferred opposite-amount candidates. Each original is consumed at most once; equal candidates, candidate ceilings, and search exhaustion return an unresolved ambiguity rather than guessing.

## Consequences

The strategy provides replayable reversal evidence with signed Decimal amounts, candidate counts, match basis, date delta, and unmatched IDs. It does not mutate journals, approve reversals, post effects, perform compensation, or replace the existing inventory/consolidation reversal workflows. Cross-engine parity, crash resume, and large benchmarks remain open.

## Rollback

Remove the reversal domain/strategy files, tests, manifest entry, ADR, and execution records. No database, source system, hosted service, release, or production state is mutated.
