# ADR 0508: Local PostgreSQL CI-failure triage

- **Date**: 2026-08-10
- **Decision**: Preserve a current local triage record for the supplied
  PostgreSQL metrics, Alembic, and native-backup failures without treating
  Windows as a substitute for the hosted Linux native-tool gate.
- **Evidence**: Against disposable local Docker PostgreSQL with the
  non-privileged application role, the focused metrics/Alembic suite passes
  11 tests. Backup contracts pass with one declared skip because the Windows
  host has no `pg_dump`/`pg_restore`/`pg_config` toolchain on PATH.
- **Boundary**: This confirms the historical metrics/migration errors are not
  reproduced locally and isolates the remaining backup prerequisite. It does
  not close hosted E-461, encrypted isolated restore, or release approval.
- **Rollback**: Remove this evidence-only ADR and E-672 entries; no product
  code, schema, or persisted customer data changes are involved.
