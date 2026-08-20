# ADR 0460: Add bounded contiguous sequence-window matching

## Status

Accepted — 2026-08-09.

## Context

The existing carry-forward strategy exposed a `sequence-window` mode name but
executed the same FIFO allocation as `carry-forward`. That did not prove a
contiguous-window algorithm or provide a bounded, explainable result for
settlements composed of adjacent obligations.

## Decision

Keep `carry-forward` as the compatibility FIFO mode and implement
`sequence-window` as a separate bounded algorithm. Obligations are canonically
ordered by business date and stable identity. Each settlement searches only
contiguous, unused windows up to the published cardinality and evaluation
budget, subject to partition/currency/date and exact Decimal tolerance rules.
The best candidate is ranked by amount difference and cardinality; equal-cost
alternatives return an explicit ambiguity instead of being guessed. Allocations
retain residuals, sequence rank, candidate count, and decision digest. Duplicate
identities fail closed.

## Consequences

The worker and strategy contract now provide genuine sequence/window evidence
with deterministic replay and no posting side effect. The mode remains
experimental and bounded: it does not claim global optimality, PostgreSQL
capacity, distributed replay, or production sizing.
