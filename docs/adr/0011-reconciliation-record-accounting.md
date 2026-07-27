# ADR-0011: Explicit Reconciliation Record Accounting

## Status

Accepted for stock-to-GL and local platform matching.

## Context

Iterating only the left-side input makes right-side orphan records disappear from the
result contract. Invalid values or dates can also be mistaken for valid zero/zero-day
values, making a reconciliation appear complete when it is not.

## Decision

Every reconciliation run must explicitly represent matched records, unmatched records
on both sides, invalid records, and policy-rejected/ambiguous records as the applicable
domain contract evolves. Invalid amounts and dates are never coerced into valid numeric
or date differences. Matching uses canonical stable identifiers and deterministic global
assignment with explicit cardinality policy.

The current platform matcher stores unmatched right-side rows with an empty `left_id`
and `match_type = unmatched_right`; the stock-to-GL result exposes data-quality frames
and an `invariants` payload while preserving the existing six-row summary API.

## Consequences

- Result counts distinguish left-side result count from total persisted evidence rows.
- Downstream exports must include both sides and use the stable exception/match IDs.
- Existing consumers should treat unknown date differences as unknown, not zero.
- Future reconciliation types must implement the same invariant contract before release.
