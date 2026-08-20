# ADR 0393: Consolidation impairment bridge is deterministic and non-posting

## Context

The consolidation workstream had acquisition fair-value, purchase-price
allocation, and deferred-tax evidence, but no bounded artifact for comparing an
approved carrying amount with an approved recoverable amount. A calculation
must not silently choose a cash-generating-unit boundary, discount rate,
valuation basis, recognition policy, or legal-book treatment.

## Decision

Add `consolidation-impairment-bridge-v1` as a local-first, pure Decimal/Money
artifact. The caller supplies one or more source-bound units, each with a
carrying amount and recoverable amount in the same registered currency. The
bridge deterministically reports per-unit impairment loss, recoverable
headroom, status, aggregate totals, source digests, and maker-checker lineage.
Units are canonically ordered by stable ID, exact arithmetic is replayed, and
the result is explicitly `posted: false`. The CLI accepts only the closed JSON
request contract and performs no database mutation or network call.

This artifact does not determine valuation methodology, statutory recognition,
reversal policy, tax effects, impairment allocation across a cash-generating
unit, journal accounts, or ERP write-back. Those remain separate reviewed
workflow decisions.

## Verification

- `tests/test_consolidation_impairment.py` covers loss/headroom arithmetic,
  permutation-stable request/result digests, maker-checker and currency
  refusal, derived-field tamper detection, JSON Schema validation, and the
  read-only CLI contract.
- `uv run --no-sync pytest -q tests/test_consolidation_impairment.py` passes.
- Ruff passes for the new domain, CLI, and tests.

## Reversibility

Remove the domain module, CLI command, schema, registry export contract, tests,
ADR, manifest entry, and execution evidence. No migration or persisted-data
rollback is required.
