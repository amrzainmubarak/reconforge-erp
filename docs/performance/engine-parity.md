# Engine Parity Evidence (Pandas vs DuckDB)

## Scope

This document covers the current local reconciliation parity checks between:

- `PandasEngine` (default local execution)
- `DuckDBEngine` (CSV/XLSX local reads through DuckDB, then shared reconciliation logic)

## What is compared

The parity test validates:

- Match and exception totals (`matched_rows`, `exception_rows`)
- Human-readable summary rows (`result.summary`)
- Deterministic reconciliation signature built from reconciled matches and exceptions

The signature is generated from:

- Stable ordered match fields (`match_id`, `move_id`, `entry_id`, match score/level, amounts, dates, references)
- Stable ordered exception fields (`exception_id`, `exception_type`, evidence and risk fields)

## Reproducible command

```bash
pytest tests/test_generator_benchmark_engines.py -k parity
```

### Environment prerequisites

- DuckDB optional dependency installed to run full cross-engine parity path.
- If DuckDB is missing, the parity test is skipped automatically.

## Acceptance criterion

- The skipped/available test is considered passed when pandas and duckdb engines produce:
  - Equal match/exceptions counts
  - Equal summary records
  - Equal reconciliation signature

If this criterion fails, the first step is to inspect:

1. Type coercion differences in `reconforge/io/readers.py`
2. Candidate generation ordering in `reconforge/reconciliation/matching.py`
3. Exception frame assembly in `reconforge/reconciliation/stock_gl.py`
