# Matching, Exceptions, And Metrics

ReconForge includes deterministic local foundations for matching jobs, exception queue management, and governed dashboard metrics.

Matching:

- Uses indexed candidate generation by reference, exact fields, or amount buckets where possible.
- Supports amount tolerance, date windows, reference matching, exact-field matching, and a controlled many-to-one option.
- Stores match jobs, rules, and results in the local DB.
- Produces explainable confidence notes such as reference matched, amount within tolerance, and date within window.

Commands:

```bash
reconforge match run --db output/reconforge.db --left output/left.csv --right output/right.csv --amount-tolerance 0.01 --date-window-days 3
reconforge match job-status --db output/reconforge.db --job-id MJ-...
reconforge match results --db output/reconforge.db --job-id MJ-...
reconforge match benchmark --db output/reconforge.db --rows 100000
```

Benchmark limits:

- The benchmark uses synthetic local rows.
- It is useful for relative local checks, not a certified scalability claim.
- Results depend on machine, SQLite settings, and input shape.

Unified exceptions:

- Queue records can reference accounts, journals, intercompany cases, controls, matching jobs, or other local workflow objects.
- SLA target dates are metadata only and do not create an SLA guarantee.

Metrics:

- Metrics are computed from local DB tables and stored with lineage.
- Current metric definitions include close completion, high-risk exceptions, review aging, evidence coverage, control effectiveness, match rate, exception aging, and period readiness.
- Metrics do not provide executive assurance or audit conclusions.
