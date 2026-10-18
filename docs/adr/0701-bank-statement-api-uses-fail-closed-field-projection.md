# ADR 0701: Bank Statement API Uses Fail-Closed Field Projection

- **Date**: 2026-08-27
- **Status**: Accepted
- **Context**: Bank Statement Control evidence is returned from local SQLite
  and tenant-scoped PostgreSQL adapters as a run envelope containing canonical
  money values, status counts, and nested bank-to-ledger decisions. Future
  adapter or storage fields must not silently expand a financial evidence
  response.
- **Decision**: Apply central allowlists to the run envelope and recursively
  project the report, amount tolerance, decision amount variance, decisions,
  and known status-count keys on create, list, and read responses. Preserve
  existing evidence digests, exact values, workspace scope, and the
  no-network/no-posting boundary. Reject malformed nested mappings rather
  than serializing them as opaque data.
- **Verification**: `tests/test_field_access.py` covers recursive report,
  money, decision, and status-count projection. The bank API test injects
  synthetic future fields at the top-level and every reviewed nested response
  level across create/list/read. Focused selectors pass 31 tests plus 1
  existing live-PostgreSQL skip; the full Python regression and required
  quality gates are recorded in the execution evidence.
- **Compatibility**: No schema, migration, persistence, permission, route,
  or evidence-digest behavior changes. This is a bounded disclosure control,
  not universal field-level authorization.
- **Rollback**: Revert E-1041 code, tests, this ADR, manifest entry, and
  execution metadata together. Do not restore unbounded adapter-row
  serialization without a replacement allowlist and regression evidence.
