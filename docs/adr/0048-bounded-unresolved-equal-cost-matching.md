# ADR 0048: Bounded Unresolved Equal-Cost Matching

- Status: Accepted
- Date: 2026-07-25
- Scope: Local stock/GL one-to-one candidate assignment, engine parity, and report provenance

## Context

The existing stock/GL matcher is deterministic: when multiple assignments have
the same cardinality and aggregate cost, stable record keys choose one result.
That preserves replay but can present an arbitrary business pairing as though it
were uniquely supported by the rules. Dense equal-reference/equal-amount cases
need an explicit conservative mode that leaves uncertainty for human review.

An exhaustive enumeration of all assignments is not acceptable. The current
matcher also has established CLI/output/signature compatibility, so changing the
default tie-break behavior would silently rewrite existing decisions and golden
evidence.

## Decision

1. Introduce two named policies:
   - `stable-tie-break-v1` remains the default and executes the established
     work-order assignment path unchanged.
   - `unresolved-equal-cost-v1` splits a work-order candidate graph into
     connected components and accepts a component only when the bounded optimum
     is unique.
2. For the conservative policy, compute the normal maximum-cardinality,
   minimum-cost selection. Prove non-uniqueness by removing each selected edge
   in turn and resolving the component. An alternative with the same cardinality
   and aggregate integer cost makes the complete connected component unresolved.
3. Bound this proof to 64 candidate edges and 32 selected-edge checks per
   component. A component over either bound becomes unresolved with
   `search_budget_exceeded`; the matcher does not continue an unbounded search.
4. Unresolved source records remain in the existing stock-without-GL and
   GL-without-stock accounting frames, but their `exception_type` is
   `ambiguous_match`. Evidence includes a stable group ID, reason, candidate
   count, optimum cardinality/cost, policy, record identity, and source
   location. No candidate from that component is approved as a match.
5. Record the policy in `StockGLReconciliationResult`, `EngineResult`, stock/GL
   CLI JSON/workbook metadata, management-pack configuration/audit evidence, and
   management-pack schema v4. The closed schema retains explicit v1/v2/v3
   compatibility branches that reject fields from later versions.
6. Advance the golden finance registry to 1.1.0. Add a six-by-six synthetic case
   with 3x3 USD and 2x2 JPY equal-cost components plus one unique EUR pair. The
   case must agree across original/permuted Pandas, DuckDB full scan, and forced
   DuckDB partition execution.
7. Keep `reconciliation-signature-v3` unchanged. It remains a versioned
   decision/exception digest, not a complete configuration digest. Golden
   expected/case/registry digests bind the policy to the signature; a standalone
   rule-and-decision digest needs a separately versioned migration.

## Consequences

- Operators may opt into a fail-closed review outcome without changing existing
  default assignments.
- Historical golden decision signatures remain byte-for-byte unchanged under
  `stable-tie-break-v1`.
- Dense ambiguity and search-budget outcomes are explicit, deterministic, and
  included in record-accounting invariants.
- The bounded alternate-edge proof performs at most 33 assignment solves per
  component (one baseline plus 32 checks). This is a safety ceiling, not a
  performance or volume claim.
- This ADR covers current stock/GL one-to-one assignment only. It does not
  implement true grouped one-to-many/many-to-many sum constraints, FX/fee
  adjustments, probabilistic matching, or live PostgreSQL execution parity.

## Rollback

Removing the conservative policy is mechanically reversible only while all
artifacts using it remain labeled and readable. Preserve management-pack v4 and
registry 1.1 evidence, and never relabel an unresolved run as stable-tie-break.
Do not roll back by deleting the budget guard, weakening equality checks, or
rewriting historical expected signatures. Restoring schema v3 as the current
writer would require a new compatibility decision and loss-free migration for
the recorded ambiguity policy.
