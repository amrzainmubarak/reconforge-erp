# ADR 0117: Exact Decimal range index

- Status: Accepted
- Date: 2026-07-27

## Context

The indexed matcher used direct amount-bucket lookup at zero tolerance, but a
positive tolerance iterated every amount bucket and parsed every key back to
Decimal for every left record. That retained exact arithmetic but approached a
full amount-index scan and made candidate generation scale with all distinct
right amounts rather than the matching range.

## Decision

Build immutable right-side amount partitions by currency and precision, sorted
by exact parsed Decimal amount and the existing stable record tie-break. Locate
the inclusive `[left - tolerance, left + tolerance]` window using `bisect_left`
and `bisect_right`, then score only the returned slice plus reference/exact-key
candidates. Query every currency-compatible partition to preserve the historical
behavior where one side omits currency; explicit unequal currencies remain
excluded. Never convert amount keys through binary float.

## Consequences

Range-bound discovery is logarithmic per compatible partition, duplicates and
both exact boundaries are retained, and existing matching/property/strategy
outputs remain unchanged. Materializing the returned slice is proportional to
the number of candidates, as it must be. Candidate caps, partition-count
budgets, timeout/search ceilings, and inclusion/exclusion evidence remain
P1-REC-003 rather than being implied by this index.

## Reversibility

The public matching signature and stored formats do not change. Reverting to a
bucket scan is mechanically possible but would restore the measured algorithmic
scaling defect and must not be described as range-indexed lookup.
