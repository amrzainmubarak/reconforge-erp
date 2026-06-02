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

## Run a Benchmark

```bash
reconforge benchmark --input benchmarks/small_1k --engine pandas --output output/benchmark
```

DuckDB can be used when the optional dependency is installed:

```bash
pip install -e ".[duckdb]"
reconforge benchmark --input benchmarks/small_1k --engine duckdb --output output/benchmark
```

If DuckDB is unavailable, ReconForge prints a clear optional-dependency message and leaves the Pandas engine unaffected.

## Outputs

- `benchmark.json`
- `benchmark.csv`
- `benchmark.md`

Metrics include runtime seconds, stock rows, GL rows, matched rows, exception rows, match rate, exception rate, report generation time, approximate memory usage, engine, and timestamp.

## Interpretation

Benchmarks are designed to guide engineering and deployment decisions. They should not be presented as universal performance claims because real export shape, hardware, rule packs, and report settings affect runtime.
