# PostgreSQL grouped matching 500-partition current local profile

## Environment

- Date: 2026-08-23
- PostgreSQL: 16.14 (`postgres:16-alpine`, local Docker service)
- Host: Windows 11, Python 3.14.6, AMD64, 16 logical CPUs
- Role: non-privileged `reconforge_app`; synthetic tenant data only
- Profile: 16 workers, 250 runs, 2 partitions per run, batch size 16
- Modes: `fx-many-to-one`, `many-to-many`, `many-to-one`, `one-to-many`, `portfolio`

## Command

```powershell
$env:RECONFORGE_TEST_POSTGRES_DSN='postgresql://reconforge_app:***@127.0.0.1:55433/reconforge'
$env:RECONFORGE_TEST_POSTGRES_ADMIN_DSN='postgresql://postgres:***@127.0.0.1:55433/reconforge'
$env:RECONFORGE_TEST_POSTGRES_APP_USER='reconforge_app'
python -m pytest -q tests/test_postgres_grouped_matching_scale.py -k '500_partition' --tb=short -rs -s
```

The focused live test passed. A direct invocation of the same public profile
returned:

```text
completed_runs=250
completed_partitions=500
result_rows=1200
expected_result_rows=1200
duplicate_result_identities=0
failed_runs=0
final_active_runs=0
per_mode_completed={fx-many-to-one: 50, many-to-many: 50, many-to-one: 50, one-to-many: 50, portfolio: 50}
observed_runtime_seconds=20.7293
effect_set_digest=d788a36aa4bd41c1b113b40da5161a68900999e642496b0c55c3d4fd1de41535
manifest_digest=aac8c126962249a2191bd26555ce263e2b0ee483519981352f58946d5c2ac527
```

## Boundaries

This is one local Docker PostgreSQL service and synthetic data. It does not
prove throughput, capacity, SLO, soak, cross-host scheduling, queue HA,
automatic failover, HA/DR, provider interoperability, statutory posting,
write-back, or production readiness.
