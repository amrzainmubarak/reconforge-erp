# PostgreSQL repeated durable-job soak — 2026-08-10

## Boundary

This is a bounded synthetic repeatability run against PostgreSQL 16 in one
disposable local Docker host. Three iterations used 64 jobs, four partitions
per job, four tenant lanes, and eight independent worker connections per
iteration. Tenant identifiers were unique per iteration while the job-ID
prefix and workload shape remained stable, allowing the effect-set digest to
be compared without crossing tenant primary-key boundaries.

## Result

- 3/3 iterations completed: 192/192 jobs and 768/768 partition effects.
- Effect-set digest was identical in all iterations:
  `4a80113a32b6af4986e9bf5e42e2462d65196022cbf34f6c21831bb306785865`.
- Duplicate effects: 0.
- Iterations with queued or running residue: 0.
- Observed runtime: 9.4047 seconds on Windows 10, Python 3.11.15,
  PostgreSQL `postgres:16-alpine`, Docker Engine local service.
- Machine observations are recorded in the JSON artifact and are not capacity
  or SLO claims.

The digest-bound JSON artifact is
`postgres-durable-job-soak-current-2026-08-10.json`.

## Verification

```text
RECONFORGE_TEST_POSTGRES_DSN=postgresql://reconforge_app:***@127.0.0.1:55433/reconforge_codex_soak_20260810
uv run --no-sync pytest -q --tb=short tests/test_postgres_durable_jobs.py -k test_live_postgres_durable_job_soak_profile -s
```

The disposable database was migrated to Alembic head, granted only the
declared application-table privileges to `reconforge_app`, and is dropped
after the verification session.

## Limitations

This does not prove distributed or multi-host soak, queue HA, automatic
failover, host loss, cross-host fairness, capacity, throughput, RPO/RTO,
production workload diversity, or production readiness.
