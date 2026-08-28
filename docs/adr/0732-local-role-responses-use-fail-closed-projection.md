# ADR 0732: Local Role Responses Use Fail-Closed Projection

- **Date**: 2026-08-28
- **Status**: Accepted
- **Context**: The local role inspection route serialized `LocalRole` models
  directly with `model_dump`, leaving its response shape coupled to future
  model fields. The role-permission response also had no shared contract for
  its nested permission collection.
- **Decision**: Apply central projections to local role records and role
  permission listings. Accept only the reviewed role identity fields and a
  string permission collection; malformed repository output fails closed with
  a bounded API error.
- **Verification**: Field-access tests cover future role and permission
  fields; the authenticated local role route test injects a future role field
  and proves it cannot cross the API boundary. Full regression and release
  gates are required before E-1072 is closed.
- **Compatibility**: Preserve the existing `/api/v1/roles` and
  `/api/v1/roles/{role_name}/permissions` response keys and values.
- **Rollback**: Revert E-1072 code, tests, this ADR, the manifest entry, and
  execution metadata together; do not restore unbounded role serialization.
