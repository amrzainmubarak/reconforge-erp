# ADR 0716: Audit Verification Uses Fail-Closed Projection

- **Date**: 2026-08-27
- **Status**: Accepted
- **Context**: The legacy `/api/v1/audit/verify` route explicitly shaped the
  local result but returned the PostgreSQL verification mapping directly. Its
  issue objects also came from dataclass dictionaries without a closed field
  boundary.
- **Decision**: Add one central `project_audit_verification` boundary and use
  it for both local and PostgreSQL verification responses. Allow only the
  verification status/count/head fields and the reviewed issue sequence and
  message fields.
- **Verification**: Focused local and PostgreSQL-shaped route tests inject
  unknown result and issue fields and prove they are absent; the existing
  authenticated workflow test verifies the compatible response shape.
- **Compatibility**: Verification status, count, head hash, issue sequence,
  and issue message remain available. Unknown fields are removed.
- **Rollback**: Revert E-1056 code, tests, this ADR, the manifest entry, and
  execution metadata together; do not restore direct PostgreSQL serialization.
