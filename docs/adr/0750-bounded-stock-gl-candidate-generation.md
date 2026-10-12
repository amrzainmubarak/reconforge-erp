# ADR 0750: Bound stock/GL candidate generation

- Status: Accepted
- Date: 2026-08-28
- Scope: One-to-one stock/GL reconciliation candidate generation

## Context

The stock/GL matcher partitioned records by work order but evaluated the full
Cartesian product within each work order. A dense same-currency work order
could therefore consume unbounded CPU and memory before the assignment or
ambiguity policy had a chance to protect the operation.

## Decision

Candidate generation is partitioned by normalized work order and currency and
has a fixed ceiling of 100,000 possible pairs per partition. A partition above
the ceiling is refused before pair evaluation. Every source row in that
partition is returned through the existing ambiguity-exception path with the
explicit reason `candidate_generation_budget_exceeded`; no partial candidate
set or partial assignment is selected. Because no assignment was evaluated,
the ambiguity's optimal-cardinality and optimal-cost evidence are null.

The existing stable tie-break and unresolved-equal-cost policies remain
compatible below the generation ceiling. This ceiling is an algorithm policy
bound, not a throughput or capacity claim.

## Rationale

Financial reconciliation must fail closed under adversarial density rather than
silently dropping candidates, timing out, or selecting from a truncated graph.
Currency partitioning preserves the matcher invariant that eligible pairs share
currency while reducing needless cross-currency scans. Explicitly exposing the
budget reason and all affected records gives reviewers an actionable exception.

## Verification

`tests/test_matching_ambiguity.py` lowers the reviewed ceiling to eight pairs
and proves that a 3-by-3 partition produces six ambiguity rows, no matches,
null optimization metrics, and a balanced record-accounting invariant. The
existing ambiguity, property, stock/GL, full regression, static, security,
package, YAML, and diff gates remain required.

## Compatibility and rollback

Partitions below the ceiling preserve the existing matching output. Revert
E-1090, this ADR, the matcher/test changes, manifest entry, and execution
records together.
