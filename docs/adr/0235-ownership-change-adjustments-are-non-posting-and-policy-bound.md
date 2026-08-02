# ADR-0235: Ownership-change adjustments remain non-posting and policy-bound

## Status

Accepted — 2026-08-02.

## Decision

Add a pure, deterministic ownership-change adjustment contract. It accepts
approved prior/new group ownership, source-bound net assets, and an explicitly
signed consideration effect. It emits three balanced reporting-currency lines:
NCI delta, consideration effect, and the parent-equity balancing effect.

The contract records policy ID/version, approval actors, source digest, exact
Decimal values, rounding delta, and deterministic request/result digests. It
never posts a journal and does not decide statutory treatment, goodwill,
purchase-price allocation, or disposal accounting. Those remain explicit
policy/application layers requiring their own review and evidence.

## Invariants

- Ownership percentages are finite Decimal values in `[0, 1]`.
- All monetary inputs use one declared reporting currency.
- Preparer and approver are distinct; approval precedes proposal preparation.
- NCI rounding is visible and the parent-equity line absorbs the rounded delta.
- The three output lines sum exactly to zero at currency precision.
- Results are `posted: false` and carry source/policy lineage.

## Rollback and compatibility

This is additive pure-domain code with no database migration or API change.
Rollback is deleting the module, tests, manifest entry, and docs. Existing
translation, worksheet, and close lifecycle contracts remain unchanged.
