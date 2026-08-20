# ADR 0378: Record the PostgreSQL application-parity batch

- **Date**: 2026-08-06
- **Status**: Accepted
- **Decision**: Retain a bounded live PostgreSQL application-parity batch as
  current evidence and keep the Finance Core API test seam aligned with its
  injected request-scope resolver and any-of scope helper.
- **Verification**: A fresh PostgreSQL 17.10 migration-head database with the
  non-privileged `reconforge_app` role passed all 117 selected tests covering
  Finance Core API, master data, close, evidence, matching, payables,
  receivables, inventory, journals, approvals, controls, execution/job scope,
  workspace attribution, and workspace-period UoW. The disposable database was
  removed after verification.
- **Boundary**: This is bounded single-node synthetic application-parity
  evidence. It does not close the full PostgreSQL parity inventory, hosted
  native backup evidence, live ERP/bank providers, write-back, HA/DR, scale or
  production readiness.
- **Rollback**: Remove the evidence entry and ADR; no runtime or data rollback
  is required.
