# ADR 0771: Enforce strict PPA and deferred-tax replay money

- Status: Accepted
- Date: 2026-08-28
- Owners: Financial Integrity / Consolidation / QA

## Context

The PPA and deferred-tax result verifiers restored persisted money through
`Money.from_canonical_dict()` and then checked the numerical reconciliation.
That protects policy provenance and arithmetic, but registry resolution
intentionally normalizes accepted currency input and exact parsing can
normalize equivalent decimal spellings. A caller who recomputed the outer
digest could therefore present a padded decimal or lowercase currency code
that retained its numerical value but did not reproduce the producer's
canonical financial artifact.

The impairment verifier is not included in this change because it already
reconstructs every persisted unit and totals and compares the complete
canonical structures before accepting the supplied digest.

## Decision

For each PPA and deferred-tax persisted money object, restore `Money`, then
require the raw `amount` string and `currency` code to exactly equal the
canonical values emitted by that restored object. Require the top-level
reporting currency to use the declared uppercase currency-code form before
any arithmetic evaluation. Missing, malformed, non-finite, padded,
scientific, policy-inconsistent, or non-canonical-currency values fail closed
even if the caller recomputes the outer result digest.

This is a replay-integrity control for non-posting calculation artifacts. It
does not determine acquisition accounting, tax recognition, tax law,
valuation, journal posting, or production readiness.

## Consequences and rollback

Producer-generated PPA and deferred-tax artifacts remain compatible. Payloads
whose financial text differs from their canonical result are now explicitly
rejected at replay time, giving all covered acquisition calculation paths the
same serialization boundary. Rollback is a metadata/code/test revert of this
slice; it does not alter financial data or deployment state.
