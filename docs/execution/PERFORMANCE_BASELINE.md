# Performance Baseline

Measured 2026-07-24. This is a smoke benchmark, not a capacity claim.

## Environment

- Microsoft Windows 11 Pro build 26200.
- AMD Ryzen 7 7435HS, 16 logical processors.
- 21,144,231,936 bytes physical memory reported.
- Python 3.14.6, pandas 3.0.3, DuckDB 1.5.5.
- Worktree/commit boundary: see `BASELINE.md`.

## Dataset

- Directory: `benchmarks/small_1k`.
- 1,000 stock rows and 1,144 GL rows.
- Canonical directory digest: SHA-256 `a520b37ed7086c9f5a350f34de2333b945273331492dfa615465ae1bc19f3ac4` over sorted `filename:file_sha256` lines encoded as UTF-8.
- Key file hashes:
  - `stock_moves.csv`: `3cc43501c4fe8b3d55f2bec69f222569870595a65806fe23d42df0939845f964`
  - `gl_entries.csv`: `0a2f42f1e7e73b0cf0ad4cdb20001a4a2788aa6df23641ee10585a37262cdda2`

## Results

| Engine | CLI runtime metric | Command wall time | Matched | Exceptions | Report generation | Memory metric |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Pandas | 0.9930s | 3.356s | 996 | 369 | 0.0037s | 0.0 MB |
| DuckDB | 1.1568s | 3.515s | 996 | 369 | 0.0040s | 0.0 MB |

Commands:

```text
reconforge benchmark --input benchmarks/small_1k --engine pandas --output output/baseline-benchmark-current-pandas
reconforge benchmark --input benchmarks/small_1k --engine duckdb --output output/baseline-benchmark-current-duckdb
```

## Interpretation limits

- Equal counts do not prove equal decisions. The separate forced-partition order-invariance test fails.
- The `0.0 MB` memory result is not credible peak-memory evidence and must be treated as an instrumentation gap.
- This run does not measure CPU utilization, candidates, ambiguity/false outcomes, crash/resume, multi-currency, or sustained load.
- No 10K, 100K, 1M, or 10M result was measured. No scale wording beyond this exact 1K dataset/environment is allowed.

## Next performance gates

1. Repair deterministic partition replay before comparing engine performance.
2. Add reliable peak-RSS measurement and output decision digest.
3. Publish generated, checksummed tiers at 10K and 100K before considering 1M.
4. Record dense duplicates, high ambiguity, bad data, grouped matching, and memory ceilings.
