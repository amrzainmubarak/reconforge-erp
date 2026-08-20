# ADR 0471: Prove grouped worker projection parity with the canonical strategy

- Status: accepted
- Date: 2026-08-09
- Decision owner: ReconForge execution owner

## Context

The PostgreSQL grouped-matching worker is deliberately persistence-free at the
matching boundary and delegates to the canonical `GroupedSubsetSumStrategy`.
Permutation and projection tests covered the output shape, but they did not
prove that the adapter continued to represent the exact direct strategy result
for every supported grouped mode.

## Decision

For each supported mode—`one-to-many`, `many-to-one`, `many-to-many`,
`partial-settlement`, and `portfolio`—construct the worker request, execute the
canonical strategy directly, and require every projected lineage
`strategy_result_digest` to equal the direct `decision_digest`. Add a one-cent
canonical amount mutation sentinel so stale or independently recalculated
projection digests fail deterministically.

## Verification

The focused grouped-worker suite passes 14 tests. Ruff and Mypy pass for the
changed test surface, and the full local Python regression exits 0 with only
declared capability skips and existing warnings.

## Boundary

This proves local adapter projection parity only. It does not prove live
PostgreSQL execution, SQL-engine parity, distributed scale, HA/DR, provider
interoperability, posting/write-back, or production readiness.

## Reversibility

Remove the additional parity tests and this ADR. No schema or public API
compatibility changes are introduced.
