# ADR 0700: Manufacturing Cost Control API Uses Fail-Closed Field Projection

- **Date**: 2026-08-27
- **Status**: Accepted
- **Context**: Manufacturing cost-control evidence is returned from local
  SQLite and tenant-scoped PostgreSQL adapters as a run envelope containing
  canonical money and quantity objects, status counts, and nested production
  decisions. Future adapter or storage fields must not silently expand a
  financial and operational evidence response.
- **Decision**: Apply central allowlists to the run envelope and recursively
  project the report, amount tolerance, maximum scrap quantity, every decision
  quantity and money value, and known status-count keys on create, list, and
  read responses. Preserve existing evidence digests, exact values, workspace
  scope, and the no-network/no-posting boundary. Reject malformed nested
  mappings rather than serializing them as opaque data.
- **Verification**: `tests/test_field_access.py` covers recursive report,
  money, quantity, decision, and status-count projection. The manufacturing
  API test injects synthetic future fields at the top-level and every reviewed
  nested response level across create/list/read. Focused selectors pass 31
  tests plus 1 existing live-PostgreSQL skip; the full Python regression and
  required quality gates are recorded in the execution evidence.
- **Compatibility**: No schema, migration, persistence, permission, route,
  evidence-digest, or lifecycle behavior changes. This is a bounded disclosure
  control, not universal field-level authorization.
- **Rollback**: Revert E-1040 code, tests, this ADR, manifest entry, and
  execution metadata together. Do not restore unbounded adapter-row
  serialization without a replacement allowlist and regression evidence.
