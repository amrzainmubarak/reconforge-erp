# ADR 0717: Consolidation Certification Uses Fail-Closed Projection

- **Date**: 2026-08-27
- **Status**: Accepted
- **Context**: Consolidation-close certification prepare, review, and read
  routes returned certification records directly. SQLite and PostgreSQL use
  different physical schemas, and future columns could therefore escape the
  HTTP boundary.
- **Decision**: Apply one central nested certification/source projection to all
  three local and PostgreSQL response paths. Preserve the reviewed lifecycle,
  actor, evidence-digest, timestamp, and version fields across both schemas.
- **Verification**: Focused local and PostgreSQL-shaped route tests inject an
  unknown certification field and prove it is absent; the existing full
  certification workflow verifies prepare, review, and read compatibility.
- **Compatibility**: Existing known certification and source fields remain
  available; only unknown adapter fields are removed.
- **Rollback**: Revert E-1057 code, tests, this ADR, the manifest entry, and
  execution metadata together; do not restore direct certification
  serialization.
