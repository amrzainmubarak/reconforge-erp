# ADR 0603: Add bounded one-to-one fee and FX grouped matching

## Status

Accepted — 2026-08-23

## Decision

The bounded grouped matcher accepts `one-to-one` in addition to its existing
group modes. Its existing Decimal fee-netting and explicit FX-rate conversion
paths are now executable for a one-to-one request, with cardinality fixed at
one on each side and the same search/tie-break/evidence envelope.

## Boundary

This adds a bounded execution path for fee-aware and FX-aware one-to-one
matching. Rates remain caller-supplied and explicitly sourced; no provider
connectivity, FX valuation, posting, or production capacity claim is made.

## Rollback

Reverting requires a versioned strategy manifest and architecture update plus
removal or migration of the one-to-one golden cases. Silent fallback to a
non-fee/non-FX matcher is not allowed.
