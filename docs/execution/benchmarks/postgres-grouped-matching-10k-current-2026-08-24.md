# PostgreSQL grouped matching 10K current local profile

## Environment

- Date: 2026-08-24
- PostgreSQL: 16.14 (`postgres:16-alpine`, local Docker service)
- Host: Windows 11, Python 3.14.6, AMD64, 16 logical CPUs
- Role: non-privileged `reconforge_app`; synthetic tenant data only
- Profile: 16 workers, 1,000 runs, 10 partitions per run, batch size 32
- Modes: `fx-many-to-one`, `many-to-many`, `many-to-one`, `one-to-many`, `portfolio`

## Command

```powershell
$env:RECONFORGE_TEST_POSTGRES_DSN='postgresql://reconforge_app:***@127.0.0.1:55433/reconforge'
$env:RECONFORGE_TEST_POSTGRES_ADMIN_DSN='postgresql://postgres:***@127.0.0.1:55433/reconforge'
$env:RECONFORGE_TEST_POSTGRES_APP_USER='reconforge_app'
python -m pytest -q tests/test_postgres_grouped_matching_scale.py -k '10k_partition' --tb=short -rs -s
```

The focused live test passed. A direct invocation of the same public profile
returned `1000/1000` completed runs, `10000/10000` completed partitions,
`24000/24000` expected rows, zero duplicate identities, zero failed runs, and
zero active runs. Each mode completed 200 runs.

- Observed runtime: `220.3637s`
- Effect-set digest:
  `1276abceb444abdf83ca62ba13a2d37f039a5326e8d7b29ed267215b5d3294b2`
- Manifest digest:
  `5ca2e2231c5f7cabda4155dde43cdfdfcbe53ed9305f885ca3667c093db42671`
- Machine-readable report: `postgres-grouped-matching-10k-current-2026-08-24.json`

## Boundaries

This is one local Docker PostgreSQL service and synthetic data. It does not
prove throughput, capacity, SLO, soak, cross-host scheduling, queue HA,
automatic failover, HA/DR, provider interoperability, statutory posting,
write-back, or production readiness.
