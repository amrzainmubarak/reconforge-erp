# PostgreSQL grouped matching 64-partition profile v1

## Declared profile

`postgres-grouped-matching/64-partitions-v1` uses four independent worker
connections to drain 32 synthetic reconciliation runs. Each run contains two
hard-key entity partitions, for 64 declared partitions. The mode sequence is
one-to-many, many-to-one, many-to-many, portfolio, and FX-aware many-to-one.
The expected output is 152 persisted result rows (2, 2, 4, 2, and 2 rows per
partition respectively, repeating across the 32 runs).

The executable profile is
`reconforge/benchmark/postgres_grouped_matching_scale.py`. The focused test
uses a five-run/ten-partition variant to keep local verification bounded while
retaining every mode and the same worker/concurrency contract.

## Evidence command

```powershell
$env:RECONFORGE_TEST_POSTGRES_DSN='postgresql://reconforge_app:reconforge_app@localhost:55433/reconforge'
$env:RECONFORGE_TEST_POSTGRES_ADMIN_DSN='postgresql://postgres:postgres@localhost:55433/reconforge'
$env:RECONFORGE_TEST_POSTGRES_APP_USER='reconforge_app'
python -m pytest -q tests/test_postgres_grouped_matching_scale.py
```

Local result on 2026-08-03: `3 passed` on PostgreSQL 16, including the live
non-superuser RLS run. Ruff passed for the profile, adapter, and tests.

## Acceptance invariants

- Every declared run and hard-key partition reaches `Complete`.
- Persisted result rows equal the declared mode-derived count.
- Result identities `(run, partition, left_id, right_id, status)` are unique.
- Failed runs and active leases are zero after the drain.
- All five modes complete with their expected counts.
- Effect-set and manifest digests are present.

## Boundaries

This is synthetic one-tenant, single-node PostgreSQL 16 evidence. Runtime is
an observation, not a throughput, capacity, SLO, soak, or production-sizing
claim. It does not cover provider connectors, statutory posting, cross-host
queue scheduling, automatic failover, or HA/DR.
