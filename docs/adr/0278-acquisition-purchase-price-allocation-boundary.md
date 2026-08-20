# ADR 0278: Non-posting acquisition purchase-price allocation boundary

## Status

Accepted for the current Phase 4 slice.

## Decision

ReconForge adds `acquisition-purchase-price-allocation-v1` as a pure,
Decimal/Money calculation artifact.  The request accepts a bounded list of
source-bound identifiable assets and liabilities, each with book value, fair
value, valuation reference, account reference, and source reference.  Inputs
are canonicalized by stable item ID so equivalent row permutations produce the
same request and result digests.

The result exposes book net assets, fair-value net assets, the exact fair-value
adjustment, and the existing acquisition fair-value/goodwill bridge.  It is
always `posted: false`, replay-verifiable, maker/checker attributed, and
balanced through the embedded bridge.  The CLI uses the shared bounded JSON
record reader and rejects unknown fields before domain construction.

## Explicit boundary

This slice does not perform purchase-price allocation judgment, tax-effect
accounting, deferred tax, impairment testing, step acquisitions, disposal
accounting, statutory statement preparation, ledger posting, PostgreSQL
persistence, source-ERP/bank write-back, or external valuation assurance.  A
negative fair-value net-assets total is rejected rather than silently balanced.
The artifact is review evidence for a later governed accounting decision.

## Verification

- `tests/test_consolidation_ppa.py` covers exact asset/liability reconciliation,
  permutation-stable digests, negative-net-assets refusal, tamper detection,
  JSON Schema validation, and the read-only CLI contract.
- `docs/schemas/acquisition_purchase_price_allocation_v1.schema.json` is the
  closed result schema.
- `finance.core` exports the versioned contract through the module registry.
