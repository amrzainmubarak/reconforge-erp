# ADR 0738: Canonical matching requires explicit currency

- Date: 2026-08-28
- Status: accepted
- Scope: persistence-independent deterministic matching when using
  `canonical-multiset-occurrence-v1`

## Context

The deterministic matching engine historically supported a legacy stock/GL
interface whose records could omit currency and therefore retained the
documented compatibility behavior. The same engine also accepts the current
`canonical-multiset-occurrence-v1` identity contract used by new persisted and
server reconciliation runs. Before this change, a canonical record with a
valid amount but no currency bypassed currency resolution and could match an
equally incomplete record. That made the amount look scoped even though its
currency was unknown.

## Decision

When `record_identity_policy` is
`canonical-multiset-occurrence-v1`, an empty or missing currency field is a
`MISSING_CURRENCY` data-quality exception. The record is invalid for matching,
and no match may be selected from it. The exception retains the normal
record-identity and source-location lineage without echoing the monetary
amount.

The `legacy-v1` identity path remains unchanged as a compatibility reader for
the existing stock/GL interface. It is not the contract for new persisted or
server reconciliation runs. Removing that compatibility behavior requires a
versioned contract migration and a new ADR.

## Consequences

- New canonical reconciliation runs fail closed instead of matching an
  unscoped amount.
- Missing currency is visible and actionable as `MISSING_CURRENCY` on both the
  result and exception surfaces.
- Present but unknown or inactive currencies continue to use their existing
  resolver errors and exception codes.
- Existing legacy callers retain their documented behavior until an explicit
  migration is approved.

## Verification and rollback

`tests/test_deterministic_matching_engine.py` proves that canonical records
without currency produce two invalid results, two `MISSING_CURRENCY`
exceptions, and no match. Ruff, Mypy, the focused matching suite, full pytest,
and release-quality gates are required evidence. Roll back the code, test,
execution records, and this ADR together; do not restore implicit currency
semantics in the canonical path without a versioned compatibility decision.
