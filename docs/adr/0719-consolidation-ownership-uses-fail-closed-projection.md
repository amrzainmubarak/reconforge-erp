# ADR 0719: Consolidation Ownership Uses Fail-Closed Projection

- **Date**: 2026-08-27
- **Status**: Accepted
- **Context**: Consolidation-ownership save and effective-resolution routes
  returned adapter-shaped ownership records directly. SQLite and PostgreSQL
  expose different storage metadata, and an added column could therefore
  cross the authenticated API boundary without review.
- **Decision**: Apply one central nested projection to the single-interest
  response and the effective-interest collection in both local and
  tenant-scoped PostgreSQL paths. Preserve the reviewed ownership, approval,
  effective-date, digest, and compatibility metadata fields; preserve the
  local workspace source marker; deny unknown adapter and envelope fields.
- **Verification**: Focused API tests inject future fields into the
  PostgreSQL-shaped save and effective-resolution responses. Field-access
  tests cover both response shapes and source envelopes; the existing local
  persistence and exact-decimal workflow remains green.
- **Compatibility**: Existing known ownership and source fields remain
  available. Unknown fields are removed rather than serialized.
- **Rollback**: Revert E-1059 code, tests, this ADR, the manifest entry, and
  execution metadata together; do not restore direct ownership serialization.
