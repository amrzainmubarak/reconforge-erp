# ADR 0123: Grouped matching explanation schema v2 with ambiguous evidence

- Status: Accepted
- Date: 2026-07-27

## Context

Explainability for grouped matching previously used `grouped-matching-explanation-v2`
inputs at runtime while public docs and manifests still referenced the v1 identity.
At the same time, new ambiguity governance required explicit tied-candidate
exposure so review teams can trace all viable sets before approval.

## Decision

Publish grouped matching explanations under a stable v2 identity across runtime and
architecture artifacts:

- `docs/architecture/matching-strategies.v1.json` is aligned to
  `grouped-matching-explanation-v2`.
- `GroupedSubsetSumStrategy` runtime manifest publication uses the same schema
  identity and exposes `ambiguous_candidate_sets` for every ambiguous outcome.
- Grouped decision payloads consistently include:
  - normalized candidate and rule inputs,
  - deterministic tie-break explanation,
  - decision and policy digests,
  - reason code and status,
  - governance-aware ambiguous candidate lists when applicable.
- Keep compatibility with the existing public grouped decision shape while adding
  the explicit v2 fields for governance and review.

## Consequences

E-112 closes P1-REC-008 by aligning the architectural strategy registry and
runtime manifest with `grouped-matching-explanation-v2` and by carrying explicit
ambiguous-candidate evidence in grouped decisions.

## Reversibility

Future schema evolutions should introduce a new explanation schema version through
manifest and compatibility tests rather than mutating existing published contract
fields in place.
