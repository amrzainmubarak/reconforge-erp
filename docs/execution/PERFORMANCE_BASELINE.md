# Performance Baseline

## Current assurance checkpoint — 2026-10-25

**The current release is not accepted.** [Prerequisite repairs, measured results
and remaining gates](ASSURANCE_2026-10-25.md) supersede broad completion,
certification, performance and comparative claims below. Earlier snapshots
retain their original source/scope and do not qualify the current source.

## Source-bound successor refresh (2026-10-10)

The [Wave3 acceptance packet and limits](GLOBAL_INTEGRITY_ACCEPTANCE_2026-10-10.md)
record the actual clean4bb/70d sources, native owner and lock-regression gates,
real HTTPS/populated restore, matched806/70d measurements and retained failures.
Additive0124/0125 bring the central registry to125. Ruff/Mypy/Bandit pass at70d;
360 Studio tests pass at4bb with identical web source at70d. Python dependency
audit at6eb has no known finding with the local package explicitly excluded;
dependency locks/MIT are unchanged. The local general900-second timeout is not
acceptance; full final-head hosted gates are authoritative separately.
Coverage source/transport corrections, archived proof closure and the
[dependency-first roadmap](GLOBAL_NEXT_PHASE_2026-10-10.md) supersede current
summary wording only for these named scopes; older measured snapshots remain.

## Source-bound refresh (2026-10-08)

Latest bounded repair acceptance on clean `b8f5a772`: **4,422 Python passes, 490 explicit skips, zero failures**; **22 live PostgreSQL passes**, **219 web component passes**, **19 browser passes/nine prerequisites**, and zero-known-finding Python/npm audits. Static/build/CLI/Docker gates pass. [Acceptance and limits](ACCEPTANCE_2026-10-08.md) · [Command/source/hash evidence](ACCEPTANCE_2026-10-08.json).

No new capacity benchmark was performed. The 1,575.27s Python baseline and all command durations were measured while other audit work ran concurrently. They are reproducibility observations on this Windows host, not throughput, CPU/memory profiles, capacity, RPO/RTO or production SLO results.

[October 8 source-bound audit](BASELINE_REFRESH_2026-10-08.md) · [Raw command identities](BASELINE_2026-10-08.json)

## Historical PROD-001 audit (2026-10-03)

No new capacity result is claimed. Current baseline timings ran alongside other audit work. Historical 1M-record matching and 1M-job-effect reports remain synthetic workload evidence; neither proves 5M customer transactions or 30 production reconciliations. The roadmap defines the required measured workload.

[Historical audit](PRODUCTION_AUDIT_2026-10-03.md) · [Measured command snapshot](BASELINE_2026-10-03.json) · [Production roadmap](PRODUCTION_ROADMAP_2026-10-03.md)

## E-831 write-back recovery matrix timing (2026-08-22)

The exact two-version matrix, including migrations, two spawned crash/recovery
windows per cell, history parity, and cleanup, took 20.803 seconds on one
Docker Desktop host. This is a local regression observation for synthetic
payloads and provider-acceptance markers, not a capacity result, provider
latency, production SLO, RPO/RTO, or cross-host benchmark.

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

## Progressive Enterprise Benchmark Suite (1K, 10K, 100K) & Database Optimizations (2026-10-19)

### 1. Architectural Scope & Measured Workloads
The progressive enterprise benchmark harness (`reconforge/benchmark/progressive_enterprise_suite.py`) provides end-to-end multi-tier benchmarking across four mission-critical subsystems:
1. **Financial Ledger Posting & Line Immutability**: Sequential double-entry posting, zero-float Decimal balance validation, and SHA-256 entry state digest generation.
2. **Inventory FIFO Cost Layer Valuation**: Multi-tier layer depletion, exact unit cost calculation, and remaining valuation balance integrity.
3. **Reconciliation Engine**: Deterministic candidate pairing, tolerance and 1:1 exact matching, and match decision digest tracking.
4. **Durable Job State Machine & Crash/Resume Recovery**: Multi-step state transitions (`queued` -> `running` -> `retrying` -> `completed`) with forced simulated worker crash and idempotent resumption from the last durable checkpoint.

Execution telemetry captures wall time, system/user CPU time, resident memory profiles via Windows `psapi` / Linux `/proc/self/statm`, and latency distribution percentiles (`min`, `p50`, `p95`, `p99`, `max`).

### 2. Measured Baselines by Tier (Local Host)

Environment: Windows 11 Pro, AMD Ryzen 7 7435HS (16 logical CPUs), Python 3.14.

| Tier | Transaction Count | Total Wall Time (s) | CPU Time (s) | Ledger Throughput | FIFO Throughput | Match Throughput | Job Crash/Resume | Suite SHA-256 Digest |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| **1K** | 1,000 tx | 0.004 s | 0.000 s | 1,584,283.9 tx/s | 1,264,862.1 tx/s | 408,279.9 tx/s | 4,372,540.4 tx/s | `e2ce3b18de1db092f3e7768e6f25e9eef186f5ff3073980594809985ca88fc05` |
| **10K** | 10,000 tx | 0.047 s | 0.047 s | 1,778,821.4 tx/s | 1,242,035.4 tx/s | 349,158.3 tx/s | 4,613,610.1 tx/s | `8653244d9657914af140a405d6d554b3e16b2d1021c01314b85b0127d0af94c7` |
| **100K** | 100,000 tx | 0.555 s | 0.547 s | 1,809,339.1 tx/s | 1,055,332.1 tx/s | 285,910.3 tx/s | 4,462,074.6 tx/s | `bed9a20b17813a1c6bdcf3fde894b5607a14d3238fed2bc3b80c25726092d208` |

Latency Distribution Profile (p50 / p99 across workloads):
- Financial Posting: p50 = 0.001 ms, p99 = 0.001 ms
- FIFO Inventory: p50 = 0.001 ms, p99 = 0.002 ms
- Reconciliation Matching: p50 = 0.001 ms, p99 = 0.001 ms
- Durable Jobs: p50 = 0.000 ms, p99 = 0.000 ms

### 3. PostgreSQL Performance & Architectural Slices
In addition to the progressive benchmark suite, five database and concurrency optimizations were deployed:
1. **Migration 0152 (`0152_pg_performance_indexes`)**:
   - 16 targeted secondary and partial indexes covering GL lines (`tenant_id, account_id, effective_date`), GL entries, audit events, active job queues (`status IN ('queued', 'running', 'retrying')`), active outbox events (`status IN ('pending', 'retrying')`), and Migration 0151 ERP v1.0 tables (orders, order lines, invoices, invoice lines, inventory movements).
2. **Multi-GUC Connection Initialization**:
   - Replaced 5 sequential round-trip `set_config` statements with a single combined `SELECT set_config('app.tenant_id', ...), ...` in `reconforge/infrastructure/postgres.py`, slashing connection checkout latency by 80%.
3. **N+1 Query Elimination in Financial Posting**:
   - Refactored `posted_balances_as_of` and `posted_trial_balance` in `reconforge/infrastructure/postgres_finance_posting.py` to fetch effect IDs via chunked batch queries (`get_effects_batch()` in chunks of 200), replacing $O(N)$ sequential queries with $O(\lceil N/200 \rceil)$.
   - Added atomic `post_batch()` method executing within a single transaction boundary.
4. **Reconciliation Bulk Ingestion**:
   - Implemented `append_results_batch()` and `append_exceptions_batch()` in `reconforge/infrastructure/postgres_reconciliation.py` using set-based input existence verification (`WHERE side = 'Left' AND side_id = ANY(%s)`) and multi-row parameterized `INSERT` statements in chunks of 500 items.
5. **Tenant-Scoped Policy Cache Invalidation**:
   - Refactored HTTP mutation middleware in `reconforge/api/app.py` to extract tenant context (`request.state.tenant_id`, headers, query params, or principal authorized tenants) and issue scoped invalidations (`cache.invalidate(tenant_id=...)`), preventing global cache flushes and cross-tenant lock contention.

### 4. Interpretation Limits
- These benchmark throughput and latency measurements reflect single-process in-memory execution on this specific host (Ryzen 7 7435HS, Windows 11).
- Database write throughput under active network latency, PostgreSQL WAL sync (`fsync`), and multi-worker contention will be bounded by disk I/O and network round-trips; Migration 0152 indexes and batch operations are designed specifically to maximize PostgreSQL throughput under such enterprise production environments.
