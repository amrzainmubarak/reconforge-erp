# ADR 0276 — Acquisition fair-value and goodwill bridge

- **Status:** Accepted
- **Date:** 2026-08-03
- **Scope:** Pure-domain consolidation evidence artifact

## Decision

Add `acquisition-fair-value-goodwill-bridge-v1` as an exact Decimal/Money,
source-bound, non-posting proposal. The bridge computes:

`consideration + NCI fair value - identifiable net assets fair value`

as either goodwill or, only when the request policy explicitly allows it, a
bargain-purchase amount. It emits a balanced bridge with visible component
lines, preparation/approval attribution, policy/source digests, and replay
verification.

## Rationale

The consolidation close needed a deterministic boundary for acquisition
fair-value work without silently inventing statutory classification or journal
posting. Making the calculation and bargain-purchase policy explicit gives
reviewers an auditable starting point and keeps the accounting decision human-
governed.

## Compatibility and limits

The artifact is additive, pure-domain, and requires no migration or network
call. It is not a purchase-price allocation engine, tax calculation, legal or
statutory accounting opinion, journal-posting path, live-rate integration, or
source-system write-back. Goodwill impairment, deferred tax, contingent
consideration, step acquisitions, disposals, and acquisition-date sequencing
remain separate policy slices.

