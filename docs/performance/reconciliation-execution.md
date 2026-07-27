# Reconciliation Execution Performance

ReconForge has two separate benchmark paths:

- `reconforge benchmark` measures the local Pandas/DuckDB file execution path.
- `reconforge benchmark-reconciliation` measures the deterministic hosted
  adapter over synthetic canonical records using explicit hard-key partitions.

The hosted benchmark is intentionally synthetic and local. It does not prove
PostgreSQL network, storage, queue, or deployment performance.

## Reproducible profiles

Run each profile on the same machine and preserve the generated JSON and
Markdown reports:

```powershell
reconforge benchmark-reconciliation --records 10000 --output output/reconciliation-benchmark-10k
reconforge benchmark-reconciliation --records 100000 --output output/reconciliation-benchmark-100k
reconforge benchmark-reconciliation --records 1000000 --output output/reconciliation-benchmark-1m
reconforge benchmark-reconciliation --records 100000 --partitions 20 --amount-fractional-digits 4 --output output/reconciliation-benchmark-100k-4dp
```

Use `--amount-fractional-digits` to stress unknown-currency precision behavior (it
defaults to `2` for legacy two-decimal fixtures). The `4` profile below exercises
exact decimal bucket keys used for unknown-precision matching:

```powershell
reconforge benchmark-reconciliation --records 10000 --amount-fractional-digits 4 --output output/reconciliation-benchmark-10k-4dp
reconforge benchmark-reconciliation --records 100000 --amount-fractional-digits 4 --output output/reconciliation-benchmark-100k-4dp
reconforge benchmark-reconciliation --records 100000 --partitions 20 --streaming --amount-fractional-digits 4 --output output/reconciliation-benchmark-100k-4dp-stream
```

The command records input counts, partition configuration, runtime, peak
traced memory, result counts, exception counts, and a deterministic output
signature. Use synthetic data only; do not run customer exports as benchmark
fixtures.

## Observed local profiles

These measurements were captured on 2026-07-23 in the shared workspace using
Python 3.14.6, Pandas 3.0.3, FastAPI 0.139.2, an AMD Ryzen 7 7435HS
(8 cores/16 logical processors), and approximately 19.69 GB RAM. Traced memory
includes the synthetic input and deterministic adapter objects:

| Total records | Partitions | Amount decimal places | Runtime | Peak traced memory | Matched | Exceptions |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 10,000 | 2 | 2 | 5.3755 s | 12.38 MB | 5,000 | 0 |
| 100,000 | 20 | 2 | 85.2630 s | 88.31 MB | 50,000 | 0 |
| 10,000 | 2 | 4 | 3.3439 s | 16.39 MB | 5,000 | 0 |
| 100,000 | 20 | 4 | 54.4183 s | 106.66 MB | 50,000 | 0 |
| 100,000 | 20 | 4 (streaming) | 57.0513 s | 15.52 MB | 50,000 | 0 |

The 1,000,000-record profile was attempted on the same machine multiple times.
Both materialized and lazy `--streaming` execution modes exceeded practical local
runtime windows without producing a completed output (`>10` minutes in-flight at
each attempt). No million-row runtime, result signature, or correctness claim is
made for this local run.

## Current limitation

The partitioned adapter bounds the matching graph only when the caller supplies
correct hard partition fields. The worker now reads those partitions through a
tenant-scoped PostgreSQL server cursor, commits each partition's output and
checkpoint hash atomically, and resumes after an explicit requeue. DuckDB also
exposes a genuine bounded CSV relation-batch iterator for ingestion experiments.
The global matcher still materializes its working sets, distributed queue
orchestration remains open, and the published 10k/100k profiles do not justify
a million-row claim; timed-out 1m attempts reinforce the need for a
lower-memory streamed global execution path and explicit benchmark budget/guardrails.
