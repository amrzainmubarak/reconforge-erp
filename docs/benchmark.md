# Benchmarking

The benchmark engine measures how ReconForge ERP performs on generated or customer-provided export folders.

## Generate Synthetic Data

```bash
reconforge generate synthetic --rows 1000 --exception-rate 0.15 --critical-rate 0.05 --seed 42 --industry workshop --output benchmarks/small_1k
```

The generator writes the canonical files expected by the reconciliation engine:

- `stock_moves.csv`
- `gl_entries.csv`
- `work_orders.csv`
- `purchase_orders.csv`
- `products.csv`
- `customers.csv`
- `old_parts_returns.csv`
- `invoices.csv`

It also writes schema-v2 `synthetic_manifest.json` with the
`exact-decimal-v1` generator policy, strict/legacy financial-input provenance,
exact scenario rates, currency precision and registry provenance, and
SHA-256/byte counts for the eight CSV files. Schema v1 remains readable as an
implicit-legacy artifact. Treat policy, seed, or algorithm changes as
benchmark-input changes and record the new manifest digest. The manifest does
not make the generated distribution representative of production data.

## Run a Benchmark

```bash
reconforge benchmark --input benchmarks/small_1k --engine pandas --output output/benchmark
```

DuckDB can be used when the optional dependency is installed:

```bash
pip install -e ".[duckdb]"
reconforge benchmark --input benchmarks/small_1k --engine duckdb --output output/benchmark
```

For the hosted deterministic execution adapter, run synthetic bounded profiles:

```bash
reconforge benchmark-reconciliation --records 10000 --output output/reconciliation-benchmark-10k
reconforge benchmark-reconciliation --records 100000 --output output/reconciliation-benchmark-100k
reconforge benchmark-reconciliation --records 1000000 --output output/reconciliation-benchmark-1m
# Lazy bounded-memory synthetic partitions; use an explicit partition count.
reconforge benchmark-reconciliation --records 1000000 --partitions 1000 --partition-max-records 2000 --streaming --output output/reconciliation-benchmark-1m-streaming
```

These profiles measure the explicit hard-key partitioned adapter only. The
`--streaming` mode generates one synthetic partition at a time and exercises
the same bounded partition matcher contract without materializing a manifest;
it still does not claim PostgreSQL network, queue, object-storage, or
production deployment performance. See [reconciliation execution performance](performance/reconciliation-execution.md).

If DuckDB is unavailable, ReconForge prints a clear optional-dependency message and leaves the Pandas engine unaffected.

## Outputs

- `benchmark.json`
- `benchmark.csv`
- `benchmark.md`

Metrics include runtime seconds, stock rows, GL rows, matched rows, exception rows, match rate, exception rate, report generation time, approximate memory usage, engine, and timestamp.

DuckDB work-order bucket sizing uses integer ceiling division over record and
work-order counts. It does not convert counts through binary float, including
beyond the exact-integer range. This governs batching only and is not evidence
for any volume/performance claim.

## Interpretation

Benchmarks are designed to guide engineering and deployment decisions. They should not be presented as universal performance claims because real export shape, hardware, rule packs, and report settings affect runtime.
