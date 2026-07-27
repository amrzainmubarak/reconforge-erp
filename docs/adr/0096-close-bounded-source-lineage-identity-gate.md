# ADR 0096: Close the bounded stable source-lineage identity gate

- Status: Accepted
- Date: 2026-07-27
- Scope: P0-006 stock/GL source-lineage exit evidence

## Context

P0-006 requires DuckDB partitioned permutation and cross-engine digest tests to
pass without deriving business identity from row index. Earlier slices replaced
row-order identity with canonical record fingerprints and multiset occurrence
identity, kept trusted physical source location as separate evidence, versioned
the reconciliation signature, fixed partition-summary ordering, and added
generated Pandas/DuckDB full-scan/forced-partition permutation properties.

The backlog also records a broader follow-up for supported Python/backend
versions and engines beyond the bounded stock/GL contract. That is a parity
matrix concern already governed by P0-009; it is not part of the P0-006 exit
sentence.

## Decision

Close P0-006 for the bounded stock/GL identity contract because:

- no row index participates in business identity;
- decimal lexical scale and row permutation do not change identity/digest;
- duplicate-identical rows use deterministic multiset occurrence identity;
- source location is distinct lineage evidence rather than invented identity;
- Pandas, DuckDB full scan, and forced DuckDB partition execution produce the
  same signature-v3 output for the declared generated cases; and
- focused and full-suite regressions pass.

Keep supported-version execution, broader backend/strategy parity, upstream
source authenticity, and physical-copy identity beyond available source
evidence outside this claim.

## Consequences

No runtime or compatibility behavior changes in this governance closure.
P0-009 remains responsible for the declared Python 3.11/3.12 and dependency
matrix. Wording must stay limited to the tested stock/GL contract and cannot
claim universal lineage, every strategy/backend, or source authenticity.

## Rollback

Reopen P0-006 if row order or lexical scale changes a bounded identity/digest,
if a row index re-enters identity, or if full/partition/cross-engine properties
diverge. Do not weaken the tests to retain completed status.
