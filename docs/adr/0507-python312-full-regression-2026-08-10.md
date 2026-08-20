# ADR 0507: Python 3.12 full local regression

- **Date**: 2026-08-10
- **Decision**: Record a complete Python 3.12 all-extra regression on the
  current tree after the historical dependency failures were reproduced and
  cleared.
- **Evidence**: The locked isolated command reaches 100% and exits 0; the
  current collection contains 2,877 tests. Capability-based PostgreSQL,
  Redis, S3/object-lock, public-network, and Windows-privilege skips remain
  declared, and only existing framework/legacy-input warnings are emitted.
- **Boundary**: This is a local Windows Python 3.12 regression, not hosted CI,
  native PostgreSQL backup evidence, independent HA/DR, provider integration,
  or release approval.
- **Rollback**: Remove this evidence-only ADR and the E-671 execution entries;
  no product code, schema, or persisted customer data changes are involved.
