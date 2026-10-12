# ADR 0705: Inventory Planning Summary API Uses Fail-Closed Field Projection

- **Date**: 2026-08-27
- **Status**: Accepted
- **Context**: The Inventory Planning summary endpoint exposes aggregate counts
  for physical-count sessions and reorder rules through both local SQLite and
  tenant-scoped PostgreSQL paths. Returning the domain summary dictionary
  directly would allow future service or adapter fields to expand the API
  response without a reviewed disclosure decision.
- **Decision**: Project the summary through the existing central allowlist on
  both backend branches before serialization. Unknown summary fields are
  dropped; the existing workspace and count fields remain compatible.
- **Verification**: `tests/test_field_access.py` covers the closed summary
  projector with a synthetic future field. The server-route contract injects
  a future summary field into the PostgreSQL-shaped response and proves it is
  absent. Focused selectors pass; the full Python regression and release gates
  are required for the final evidence record.
- **Compatibility**: This changes disclosure only. It does not alter count,
  reorder, quantity, approval, authorization, or persistence behavior.
- **Rollback**: Revert E-1045 code, tests, this ADR, the manifest entry, and
  execution metadata together. Do not restore direct summary serialization
  without a reviewed allowlist and regression coverage.
