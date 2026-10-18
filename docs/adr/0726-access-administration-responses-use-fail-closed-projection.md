# ADR 0726: Access Administration Responses Use Fail-Closed Projection

- **Date**: 2026-08-27
- **Status**: Accepted
- **Context**: Access administration routes serialized permission, role, and
  user-role assignment dataclasses directly with `asdict(...)`. These
  authenticated responses define authorization lifecycle state and must not
  rely only on framework response-model filtering to contain future adapter
  fields.
- **Decision**: Apply central projections to permission records, role pages,
  role lifecycle mutations, and user-role assignment responses. Invalid nested
  role/page shapes fail closed with bounded API errors. Policy-analysis
  artifacts remain a separate response contract.
- **Verification**: Field-access tests inject unknown fields at permission,
  role, pagination, nested role-change, and assignment boundaries.
  Authenticated API tests inject future fields through the route serialization
  seam and prove they do not escape. Full regression and release gates are
  recorded before closure.
- **Compatibility**: Preserve existing role lifecycle, permission names,
  assignment state, pagination, and audit identifiers.
- **Rollback**: Revert E-1066 code, tests, this ADR, the manifest entry, and
  execution metadata together; do not restore direct access-response
  serialization.
