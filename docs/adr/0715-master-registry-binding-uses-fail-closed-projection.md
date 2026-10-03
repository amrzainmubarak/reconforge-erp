# ADR 0715: Master Registry Binding Uses Fail-Closed Projection

- **Date**: 2026-08-27
- **Status**: Accepted
- **Context**: Currency Registry reconciliation was projected centrally, but
  the explicit registry-binding mutation returned the SQLite/PostgreSQL
  binding mapping directly and exposed its server source envelope separately.
- **Decision**: Add one central `project_master_registry_binding` boundary and
  apply it to both local and server binding responses. Project the nested
  binding fields and the source envelope before serialization.
- **Verification**: Focused API projection tests inject unknown binding fields
  into local and PostgreSQL-shaped results and prove they are absent while the
  reviewed binding and source fields remain unchanged.
- **Compatibility**: Registry version, digest, timestamps, actor, and the
  existing server source marker remain available. Only unknown response fields
  are removed.
- **Rollback**: Revert E-1055 code, tests, this ADR, the manifest entry, and
  execution metadata together; do not restore direct result serialization.
