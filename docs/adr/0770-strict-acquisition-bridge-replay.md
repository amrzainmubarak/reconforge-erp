# ADR 0770: Enforce strict acquisition bridge replay amounts

- Status: Accepted
- Date: 2026-08-28
- Owners: Financial Integrity / Consolidation / QA

## Context

The acquisition fair-value/goodwill bridge already emitted canonical `Money`
objects and bound the result to a digest. Its replay verifier nevertheless
converted persisted summary and line amount strings directly with `Decimal`.
That allowed a caller who could recompute the outer digest to replace a
canonical amount with scientific notation or a non-canonical decimal spelling.
The resulting artifact would be internally re-signed but would no longer obey
the financial serialization contract used by the producer and related
consolidation bridges.

## Decision

Restore every persisted acquisition summary and line amount through
`Money.from_canonical_dict()`. Require the embedded currency policy and
registry provenance to validate, require the reporting currency to match, and
require both money and reporting currency codes to retain their canonical
uppercase representation. Apply the non-negative constraint to the goodwill
and bargain-purchase summaries before balance evaluation. A re-signed payload with missing,
malformed, non-canonical, non-finite, policy-inconsistent, or mismatched
currency money fails closed.

The result remains a non-posting calculation artifact. This decision does not
assert statutory acquisition accounting, valuation assurance, tax treatment,
or journal-posting authority.

## Consequences and rollback

Valid producer-generated artifacts remain replayable, while semantically
invalid re-signed financial payloads are rejected before arithmetic. The
verifier now shares the canonical-money boundary used by the PPA,
deferred-tax, impairment, and ownership-change replay paths. Rollback is a
metadata/code/test revert of this slice; it does not modify financial data or
deployment state.
