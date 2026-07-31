# ADR 0122: Explicit grouped matching ambiguity governance

- Status: Accepted
- Date: 2026-07-27

## Context

`bounded-grouped-subset-sum@1.0.0` already enforces exact-sum, cardinality, and
date-partition constraints for true grouped candidate evaluation. Before this slice,
bounded candidates that shared an identical minimum business cost could still be
reduced to one arbitrary selected group, which made exception governance and audit
review inconsistent under deterministic replay.

## Decision

Treat tied grouped minima as unresolved ambiguity by default:

- Compare candidates by the published deterministic business-cost tuple
  `(difference, cardinality, date_span, stable record identities)`.
- If more than one candidate has the exact minimum business-cost tuple, return
  `status="ambiguous"` with `reason_code="GROUP_MATCH_AMBIGUOUS"`.
- Emit every tied candidate set through a new immutable payload field
  `ambiguous_candidate_sets`, ordered deterministically by stable record IDs.
- Keep matched behavior unchanged when there is exactly one minimum-cost candidate.
- Keep the search-budget overflow path as fail-closed `GROUP_SEARCH_BUDGET_EXCEEDED`
  and maintain the one-group-per-request invariant.

## Consequences

E-111 closes P1-REC-007 by making unresolved group ties explicit for governed
review instead of arbitrary deterministic-looking selection. The decision now
documents the governance artifact as evidence, while preserving all other existing
grouped contracts and limits.

## Reversibility

If a future policy requires automatic tie-breaking for a specific domain use case,
introduce an explicit policy flag and versioned strategy revision. The default
behavior here remains ambiguity-first and fail-closed.
