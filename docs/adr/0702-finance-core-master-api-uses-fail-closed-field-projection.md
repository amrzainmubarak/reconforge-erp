# ADR 0702: Finance Core Master API Uses Fail-Closed Field Projection

- **Date**: 2026-08-27
- **Status**: Accepted
- **Context**: Finance Core master resources are returned from local SQLite,
  tenant-scoped PostgreSQL, and a bounded legacy ledger adapter. Charts of
  accounts, accounts, dimensions, dimension values, and journals contain
  accounting identifiers and posting-policy fields. Future adapter or storage
  fields must not silently expand these responses.
- **Decision**: Apply central allowlists to every reviewed Finance Core master
  list and mutation response. Preserve the deliberate union of local,
  tenant-scoped, and legacy-compatible field names, including the server
  workspace marker where that adapter shape exposes it. Drop unknown fields
  before serialization while leaving persistence, scope, permission, and
  accounting invariants unchanged.
- **Verification**: `tests/test_field_access.py` covers all five master
  resource projectors. Existing server Finance Core route tests inject a
  synthetic future adapter field and prove it is absent from projected chart
  and journal responses. Focused selectors pass 42 tests; full Python
  regression and required quality gates are recorded in the execution
  evidence.
- **Compatibility**: No schema, migration, persistence, permission, route,
  pagination, or accounting behavior changes. This is a bounded disclosure
  control, not universal field-level authorization.
- **Rollback**: Revert E-1042 code, tests, this ADR, manifest entry, and
  execution metadata together. Do not restore unbounded master-row
  serialization without replacement allowlists and regression evidence.
