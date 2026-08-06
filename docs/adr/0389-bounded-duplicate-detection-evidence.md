# ADR 0389: Publish bounded duplicate-detection evidence without silent de-duplication

- **Date:** 2026-08-06
- **Status:** Accepted
- **Scope:** Matching strategy contract and canonical duplicate lineage

## Context

The reconciliation engine already preserves duplicate occurrences in its legacy
matching path, but duplicate detection was not independently addressable as a
versioned strategy.  A caller could therefore discover duplicate rows only as a
side effect of a broader match.  Financial inputs must not be silently dropped,
and identical values represented as `10` and `10.00` must have one deterministic
financial fingerprint without introducing binary floating point.

## Decision

Add the experimental `bounded-duplicate-detection@1.0.0` strategy.  It groups
each side independently by a canonical projection (amount, date, reference,
currency, and partition by default, or an explicit comma-separated field list),
normalizes exact Decimal amounts, rejects binary floats and malformed amounts,
sorts by fingerprint and stable record identity, and emits every occurrence with
an ordinal.  It never deletes, rewrites, or automatically merges records.

The strategy has published per-side and total evaluation ceilings.  Exceeding a
ceiling returns an explicit `ambiguous` result with no partial groups.  Duplicate
groups are exposed both in the result and in the exception evidence, while
unique fingerprints remain visible for complete coverage.  The result and
strategy request digests are permutation-invariant.

## Verification

`tests/test_duplicate_detection_strategy.py` and the existing matching strategy
contract suite pass.  The focused tests cover canonical Decimal equivalence,
side-scoped duplicate groups, occurrence lineage, custom identity fields,
permutation-stable digests, binary-float and duplicate-identity rejection, the
published input ceiling, and architecture-document alignment.  Ruff and Mypy
pass on the new source files.

## Boundary

This is an experimental exact-duplicate evidence strategy.  It does not claim
near-duplicate similarity, probabilistic matching, fraud detection, automated
financial approval, provider interoperability, PostgreSQL scale, or production
readiness.  Existing legacy and grouped matching contracts remain unchanged.

## Reversibility

Remove the strategy/domain/test/manifest and this ADR and architecture entry;
there is no database migration or data mutation.
