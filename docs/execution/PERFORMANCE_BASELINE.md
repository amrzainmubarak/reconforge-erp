# Performance Baseline

Measured 2026-07-27. This is a deterministic reconciliation harness baseline, not
a full production capacity claim.

## Environment

- Microsoft Windows 11 Pro build 26200.
- AMD Ryzen 7 7435HS, 16 logical processors.
- 21,144,231,936 bytes physical memory reported.
- Python 3.14.6, pandas 3.0.3, DuckDB 1.5.5.
- Worktree/commit boundary: see `BASELINE.md`.

## Dataset

- Deterministic synthetic reconciliation profiles:
  - `10k`: 10,000 total rows (5,000 left + 5,000 right), 2 partitions.
  - `100k`: 100,000 total rows (50,000 left + 50,000 right), 20 partitions.
- Engine: `local-deterministic-partitioned` (single-process, local algorithm path).
- Seed: `7`, partition max rows: `10,000`, amount fractional digits: `2`.
- Suite output:
  - `output/reconforge-plan-benchmarks/plan1-3/reconciliation-execution-benchmark-suite.json`
  - `output/reconforge-plan-benchmarks/plan1-3/reconciliation-execution-benchmark-suite.md`
- Per-profile output:
  - `output/reconforge-plan-benchmarks/plan1-3/10k/reconciliation-execution.json`
  - `output/reconforge-plan-benchmarks/plan1-3/100k/reconciliation-execution.json`

## Results

| Profile | Runtime (s) | CPU time (s) | Peak MB | Results | Matched | Exceptions | Signature | Candidate total | Candidate max | Candidate mean |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: |
| 10k | 10.3894 | 10.4219 | 44.27 | 5,000 | 5,000 | 0 | `4d1a8c3469e4c4a266c0cbcfc4ff57dc93addc2ff078cbcad677045f5b3ca2ea` | 5,000 | 1 | 1.0 |
| 100k | 141.8710 | 142.6562 | 354.43 | 50,000 | 50,000 | 0 | `9e10d8d7ce5d6e280811a505de78607840c72117045636b461cde984434f10cc` | 50,000 | 1 | 1.0 |

Baseline signatures and file digests:

- Suite signature: `f370bf114f1d7414642068ba555c94fe7c8ef076d6934a3a2d8c93acead48344`
- 10k output SHA-256: `53ab682fea85e428507b26f0e315e34d69bfd71982f0c36315ce66cbcdc9c8f8`
- 100k output SHA-256: `40927c53c39c24cc271278ecd54fdc970e801cbc7a2df1b71e6b4e225d1a6220`

Command:

```text
python - <<'PY'
from pathlib import Path
from reconforge.benchmark.reconciliation_execution import (
    ReconciliationExecutionBenchmarkProfile,
    run_reconciliation_execution_benchmark_suite,
)

run_reconciliation_execution_benchmark_suite(
    (
        ReconciliationExecutionBenchmarkProfile(profile_id="10k", total_records=10_000, partition_count=2, seed=7),
        ReconciliationExecutionBenchmarkProfile(profile_id="100k", total_records=100_000, partition_count=20, seed=7),
    ),
    output_dir=Path("output/reconforge-plan-benchmarks/plan1-3"),
)
PY
```

## Interpretation limits

- Equal counts do not prove equal decisions; signature equality is also validated at the same profile boundary in this slice.
- This table now includes deterministic candidate counters and suite digests for profile closure; it does not prove database-backed durability, distributed worker behavior, 1M/10M scale, or sustained load.
- This is local single-host and single-process evidence with explicit CPU/peak-memory capture; no network/database connector, crash-restart replay, or air-gap network-dispersed execution effects are included.
- No 1M/10M profile claims are made.

## Next performance gates

1. Add `match`/`exception` and ambiguity outcome percentages in a normalized format.
2. Add crash/restart replay benchmarks for this deterministic suite.
3. Add 1M synthetic profile benchmark under controlled memory budget.
4. Add grouped-matching, grouped ambiguity, and high-ambiguity candidate-density profiles to close throughput completeness.
