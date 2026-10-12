# ADR 0714: Master Registry Reconciliation Uses Fail-Closed Projection

- **Date**: 2026-08-27
- **Status**: Accepted
- **Context**: The Currency Registry reconciliation endpoint returned the
  local and PostgreSQL result mappings directly, even though the same nested
  contract was already projected when embedded in the master-data snapshot.
- **Decision**: Add one central `project_master_registry` boundary and apply
  it to both server and local reconciliation responses, including the nested
  registry details, issues, and binding fields.
- **Verification**: The master-data projection test injects unknown top-level
  and nested fields into the local route result and proves they are absent.
- **Compatibility**: Reconciliation status, digests, counts, issue details,
  binding state, and currency policy behavior are unchanged; only unknown
  response fields are removed.
- **Rollback**: Revert E-1054 code, tests, this ADR, the manifest entry, and
  execution metadata together; do not restore direct result serialization.
