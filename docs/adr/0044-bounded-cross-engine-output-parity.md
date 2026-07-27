# ADR 0044: Bounded Cross-Engine Output Parity

- Status: Accepted
- Date: 2026-07-25
- Scope: Stock/GL Pandas and DuckDB full-scan/partitioned output contracts

## Context

Fixed datasets proved signature-v3 parity between Pandas and DuckDB, including
a forced partition path, but they did not generate combinations of identical
duplicates, invalid financial cells, missing dates, stable ties, and input
permutations through the actual CSV readers. P0-009 requires both decisions and
canonical digests to agree across engines. A generated minimized example with
one exact pair exposed a narrower output drift: DuckDB's partition merger sorted
summary metrics alphabetically while the Pandas/full-scan contract retained the
domain order. The decision digest was equal, but the public summary sequence was
not.

## Decision

1. Treat the established stock/GL summary metric order as part of the engine
   output contract: matched, unmatched stock, unmatched GL, value differences,
   date differences, then reference mismatches.
2. Make DuckDB's partition merger reindex aggregated metrics to that order.
   Do not change `reconciliation-signature-v3`; source row remains excluded and
   canonical multiset record identity remains included.
3. Add a derandomized file/engine property with ten bounded generated examples
   plus explicit exact and duplicate/invalid cases. Each case runs original and
   permuted CSV inputs through Pandas, DuckDB full scan, and forced DuckDB
   partition execution and compares:
   - signature and signature version;
   - financial-input and record-identity policies;
   - row/match/exception counts; and
   - ordered summary metrics.
4. Keep one to seven records per side and no timing deadline. The property is a
   correctness gate, not a benchmark.
5. Disclose the measured version boundary: Windows/Python 3.14.6, Pandas 3.0.3,
   and DuckDB 1.5.5. This local proof does not satisfy the declared Python
   3.11/3.12 or multi-version matrix.

## Consequences

- Full-scan and partitioned engine outputs now share one observable summary
  order as well as one signature for the bounded generated cases.
- A future difference shrinks to a reproducible CSV-level example that exercises
  the real readers instead of only the pure matcher.
- Partitioned summary row order intentionally changes from alphabetical to the
  established domain order. Metric names and counts do not change.
- P0-009 moves to in progress. Supported-version CI, broader datasets/backends,
  dense multi-currency ambiguity, and golden manifest evidence remain open.

## Rollback

Reverting the summary reindex is safe only together with an explicitly
versioned output contract and compatibility reader. Do not weaken the parity
test to compare unordered summaries or omit the partition path; retain any
future minimized counterexample as an explicit regression.
