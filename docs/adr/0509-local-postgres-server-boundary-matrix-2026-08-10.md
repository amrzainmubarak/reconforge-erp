# ADR 0509: Current local PostgreSQL server-boundary matrix

- **Date**: 2026-08-10
- **Decision**: Retain a disposable PostgreSQL 16 server-boundary matrix
  result covering the current API, control, migration, and durable-job paths.
- **Evidence**: A fresh database reached Alembic head `0086_pg_close_reopened`
  and the non-privileged `reconforge_app` role passed the selected foundation,
  identity, ledger, evidence, reconciliation, metrics, migration, sector API,
  and durable-job backpressure/10K suites. The database was dropped after the
  run.
- **Boundary**: One local Docker host and synthetic tenant data. Native backup
  binaries were unavailable on Windows, so encrypted native backup/restore,
  hosted CI, independent HA/DR, live providers, and production readiness are
  not promoted.
- **Rollback**: Remove this evidence-only ADR and E-673 execution entries; no
  product code or persistent customer data changes are involved.
