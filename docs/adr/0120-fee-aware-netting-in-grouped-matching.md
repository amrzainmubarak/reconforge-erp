# ADR 0120: Fee-aware grouped matching with explicit netting mode

- Status: Accepted
- Date: 2026-07-27

## Context

The new `bounded-grouped-subset-sum` strategy already supports exact grouped
sum constraints, but grouped groups with fees currently had no explicit policy for
whether reconciliation compares gross amounts or net amounts after fee impact. That
gap weakens auditability and makes reconciliation exceptions harder to explain for
fee-bearing settlements.

## Decision

Introduce explicit netting policy and fee fields for grouped matching:

- Add `netting_mode` with values `gross` (default) and `net` to `GroupedMatchPolicy`.
- Add `fee` as a first-class `GroupedRecord` field and aggregate both
  fee totals and net totals when evaluating candidate groups.
- Keep `gross` behavior unchanged for backward compatibility.
- In `net` mode compare group net totals (`gross - fees`) while still carrying and
  validating fee totals for explainability.
- Expose matching request fields `left_fee_field`, `right_fee_field`, and
  `netting_mode` on the strategy contract, with strict validation.

## Consequences

E-109 closes P1-REC-005 by making grouped matching deterministic with explicit
fee and netting policy. Outputs now include fee totals and net totals to support
reconciliation review. The change is isolated to grouped strategy strategy/domain
contracts and does not alter other matching strategies.

## Reversibility

The change is versioned through strategy manifest request fields and policy values.
It can be superseded by a new strategy version (for example with FX-inclusive
netting math) without altering compatibility contracts.
