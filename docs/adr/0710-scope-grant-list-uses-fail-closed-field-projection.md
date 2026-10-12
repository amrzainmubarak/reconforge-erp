# ADR 0710: Scope-Grant Lists Use Fail-Closed Field Projection

- **Date**: 2026-08-27
- **Status**: Accepted
- **Context**: The scope-authority list endpoint returned PostgreSQL grant
  dictionaries directly without a response model or central field boundary.
  Future storage columns could therefore enter an administrative response
  unintentionally.
- **Decision**: Project every listed scope grant through one central allowlist
  containing only the grant identity, principal, scope, and grant-audit fields.
  Unknown repository fields are dropped before serialization.
- **Verification**: `tests/test_field_access.py` covers the grant allowlist and
  `tests/test_api_scope_grants.py` injects a future repository field through
  the authenticated HTTP list boundary and proves it is absent.
- **Compatibility**: Grant creation, revocation, tenant enforcement, and
  immutable PostgreSQL storage are unchanged. This is bounded read disclosure
  control, not a new authorization engine.
- **Rollback**: Revert E-1050 code, tests, this ADR, the manifest entry, and
  execution metadata together; do not restore direct repository serialization.
