# Performance Baseline

## E-830 bounded receiver recovery timing (2026-08-22)

The exact two-node synchronous receiver topology measured fencing start through
promotion and exact replay of the already remote-applied identity. PostgreSQL
16.14 measured 6.168 seconds and PostgreSQL 17.10 measured 6.199 seconds; both
were below the explicit 60-second drill ceiling. The complete two-version
matrix, including topology creation, two base backups per version, partition,
re-seed, restart, verification, and cleanup, took 64.067 seconds. Acknowledged
synthetic-effect RPO was zero transactions in both cells. These measurements
come from one Docker Desktop host and one failure domain with manual control;
they are regression ceilings and local observations, not production capacity,
availability, RPO/RTO commitments, automatic-failover SLOs, or cross-host
benchmarks.

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
- Version-controlled suite evidence:
  - `docs/execution/benchmarks/phase2/reconciliation-execution-benchmark-suite.json`
  - `docs/execution/benchmarks/phase2/reconciliation-execution-benchmark-suite.md`
- Version-controlled per-profile evidence:
  - `docs/execution/benchmarks/phase2/10k/reconciliation-execution.json`
  - `docs/execution/benchmarks/phase2/100k/reconciliation-execution.json`

## Results

| Profile | Runtime (s) | CPU time (s) | Peak MB | Results | Matched | Exceptions | Signature | Candidate total | Candidate max | Candidate mean |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: |
| 10k | 10.3894 | 10.4219 | 44.27 | 5,000 | 5,000 | 0 | `4d1a8c3469e4c4a266c0cbcfc4ff57dc93addc2ff078cbcad677045f5b3ca2ea` | 5,000 | 1 | 1.0 |
| 100k | 141.8710 | 142.6562 | 354.43 | 50,000 | 50,000 | 0 | `9e10d8d7ce5d6e280811a505de78607840c72117045636b461cde984434f10cc` | 50,000 | 1 | 1.0 |

Baseline signatures and file digests:

- Suite signature: `ae0fd0bae04630491c25d0dc9756121ae9e9a457b0ebfab94fdcdba6b659e59e`
- 10k output SHA-256: `6dd61519ffdc9f8e63dcc18dadfe203a288a4c5cc6d57ef321e0dfbf2e3c586f`
- 100k output SHA-256: `343408e5fa82c47b4a523ff06dfe09af48bc0f614d5ab47e7d075ddae0bbc584`
- Published JSON uses canonical LF newlines and a final newline, so the file digests are stable across supported operating systems.

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
    output_dir=Path("docs/execution/benchmarks/phase2"),
)
PY
```

## Interpretation limits

- Equal counts do not prove equal decisions; signature equality is also validated at the same profile boundary in this slice.
- This table now includes deterministic candidate counters and suite digests for profile closure; it does not prove database-backed durability, distributed worker behavior, 1M/10M scale, or sustained load.
- This is local single-host and single-process evidence with explicit CPU/peak-memory capture; no network/database connector, crash-restart replay, or air-gap network-dispersed execution effects are included.
- No 1M/10M profile claims are made.

## Evidence index

`docs/execution/benchmarks/INDEX.v1.json` is a closed index of selected
machine-readable 10K/1M and PostgreSQL profiles. It verifies each artifact's
repository-relative path, SHA-256, profile identity, declared digest fields,
and non-production claim boundary without running the workload:

```text
uv run --no-sync python .github/scripts/verify_benchmark_index.py --root .
```

The index is a traceability gate, not a new performance result. It does not
upgrade `partial` PostgreSQL entries, infer capacity from runtime, or replace
hosted cross-engine, distributed, or production-sizing evidence.

## Next performance gates

1. Add `match`/`exception` and ambiguity outcome percentages in a normalized format.
2. Add crash/restart replay benchmarks for this deterministic suite.
3. Add 1M synthetic profile benchmark under controlled memory budget.
4. Add grouped-matching, grouped ambiguity, and high-ambiguity candidate-density profiles to close throughput completeness.

## E-674 PostgreSQL repeated durable-job observation (2026-08-10)

The bounded `postgres-durable-job-soak/repeated-small-tier-v1` profile ran
three 64-job/256-effect iterations on the local disposable PostgreSQL 16
service. The observed wall time was 9.4047 seconds for 192 jobs; all effect
digests were equal and queues drained. This timing is hardware- and workload-
dependent and is deliberately not a throughput, capacity, SLO, or sizing
claim. Distributed soak and production scheduling remain future gates.
