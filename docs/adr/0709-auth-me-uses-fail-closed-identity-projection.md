# ADR 0709: Auth Me Uses Fail-Closed Identity Projection

- **Date**: 2026-08-27
- **Status**: Accepted
- **Context**: `/api/v1/auth/me` assembled a dynamic dictionary and returned it
  without a response model or central projection. Local users, server users,
  and service accounts have intentionally different optional identity fields,
  so an internal field added later could be disclosed accidentally.
- **Decision**: Apply one central identity allowlist before serialization and
  recursively project the authorized workspace, organization, and legal-entity
  scope envelope. Preserve the existing local/server/service-account fields;
  drop unknown top-level and nested scope fields.
- **Verification**: `tests/test_field_access.py` covers the identity and scope
  allowlists. `tests/test_api_auth.py` injects a future identity field through
  the authenticated HTTP boundary and proves it is absent. Focused and full
  release-quality gates are required for the evidence record.
- **Compatibility**: This changes response disclosure only. It does not alter
  authentication, session rotation, role lookup, scope evaluation, or token
  handling.
- **Rollback**: Revert E-1049 code, tests, this ADR, the manifest entry, and
  execution metadata together. Do not restore unbounded identity serialization
  without a reviewed response contract.
