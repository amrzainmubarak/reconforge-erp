# ADR 0118: Fail-closed candidate budgets

- Status: Accepted
- Date: 2026-07-27

## Context

Range indexing bounds discovery cost for sparse data, but dense equal references
or wide tolerances can still return a very large slice. Truncating that slice
and matching the first candidates would create a deterministic-looking but
financially arbitrary decision. Wall-clock timeout alone is machine-dependent
and cannot define reproducible outcomes.

## Decision

Adopt `indexed-candidate-budget-v1`: at most 10,000 indexed candidates for one
left record and 1,000,000 candidate evaluations for one run. Count the stable
deduplicated candidate set before scoring. If either ceiling is exceeded, score
and select none for that left record and emit an explicit `Ambiguous` result
plus a `matching_ambiguity` exception containing policy, observed count,
ceiling, inclusion basis, and exclusion reason. Process left records in the
existing stable identity order, making the total search budget reproducible
under row permutation. Publish both ceilings in the strategy manifest.

## Consequences

Dense inputs fail safe without partial selection, and operators receive an
actionable reason rather than an empty unmatched result. The deterministic
evaluation ceiling is the authoritative search budget; a wall-clock watchdog
may later stop infrastructure work but must not silently change business
decisions. Configurable policies, per-partition caps, grouped-search budgets,
and explanation schema v2 remain later tasks.

## Reversibility

Changing a ceiling changes execution semantics and requires a new strategy or
policy version plus impact evidence. Removing the ambiguity outcome would
restore unbounded resource use or unsafe truncation.
