# ADR 0216: Bounded partial settlement keeps residuals visible

## Context

Grouped matching already supports exact one-to-many, many-to-one, and
many-to-many/netting decisions.  Real settlement workflows also receive a
payment that covers only part of a bounded invoice or statement group.  Treating
that as an exact match would hide an accounting residual.

## Decision

1. Add `partial-settlement` as an explicit grouped strategy mode in the domain,
   Reconciliation-as-Code contract, runtime manifest, and published strategy
   document.
2. Enumerate the same partitioned, date-bounded subsets under the existing
   cardinality and search ceilings.  Exact equality wins first; otherwise a
   partial candidate requires positive net totals and settles exactly the
   smaller side.
3. Return `settled_amount`, `left_residual`, and `right_residual` in the
   immutable decision and digest.  The reason code is
   `PARTIAL_SETTLEMENT_PROPOSAL`; no ledger posting, write-back, or automatic
   residual closure occurs.
4. Among partial candidates, maximize settled amount, then minimize the
   residual gap and date span.  Equal candidates remain unresolved under the
   existing deterministic ambiguity contract.

## Consequences

The strategy surface now expresses a bounded, explainable partial settlement
proposal with visible remaining balances and explicit replay identity.  It does
not yet select multiple non-overlapping groups in one run, implement
carry-forward/sequence/reversal-specific logic, or prove mutation, crash/resume,
cross-engine, or large-scale benchmark behavior.

## Rollback

Remove the mode, residual fields, tests, manifest/schema/documentation changes,
and this ADR.  No migration, source-system mutation, connector call, release,
or deployment rollback is required.
