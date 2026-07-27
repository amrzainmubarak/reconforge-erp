# ADR 0119: Bounded true grouped matching

- Status: Accepted
- Date: 2026-07-27

## Context

The existing platform flags relax bipartite edge capacities and can reuse a
record across individually equal pairs. They do not prove that the sums of two
record groups reconcile. Relabeling that behavior would hide a financial
semantic gap. Unbounded subset enumeration would instead create denial-of-
service and unpredictable-runtime risk.

## Decision

Add the separate experimental strategy
`bounded-grouped-subset-sum@1.0.0`. Its pure domain model enforces exact Decimal
sums, a common currency, an explicit common partition, date and cardinality
constraints, stable-identity ordering, and a deterministic 25,000-evaluation
search ceiling. The application boundary rejects binary/non-finite money and
noncanonical dates. One-to-many and many-to-one require at least two records
on the grouped side; many-to-many requires at least two on both sides.

Select by difference, cardinality, date span, and stable identities. If the
search budget is crossed, return an explicit ambiguous decision and select
nothing. Publish algorithm, modes, explanation schema, tie-break, and limits
through the matching-strategy contract. Preserve the old pair-capacity flags
as compatibility behavior and document that they are not grouped-sum matching.

## Consequences

E-108 supplies a bounded, reproducible first grouped use case without changing
the CLI or persistence schema. The 64-record input and four-per-side group
ceilings are safety limits, not scale claims. Batch non-overlap assignment,
netting, fee/FX behavior, ambiguity governance, and benchmarks remain later
slices.

## Reversibility

The strategy is separately versioned and experimental. It can be removed or
superseded without changing the indexed one-to-one adapter or legacy CLI
outputs. Changing financial constraints or selection order requires a new
strategy version.
