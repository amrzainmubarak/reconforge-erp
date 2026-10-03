# ADR 0725: Identity Administration Responses Use Fail-Closed Projection

- **Date**: 2026-08-27
- **Status**: Accepted
- **Context**: Identity administration routes serialized user and session
  dataclasses with `asdict(...)` directly. These authenticated responses carry
  lifecycle metadata and must not depend only on framework response-model
  filtering to contain future adapter fields.
- **Decision**: Apply central projections to identity-user and identity-session
  records, paginated user/session envelopes, user-status transitions, and
  session revocations. Invalid nested shapes fail closed with bounded API
  errors. The reviewed contract excludes credentials, tokens, raw IP/user-agent
  values, and unapproved future fields.
- **Verification**: Field-access tests inject unknown fields into identity
  records, pagination, and nested mutation responses. Authenticated API tests
  inject future fields through the route serialization seam and prove they do
  not escape. Full regression and release gates are recorded before closure.
- **Compatibility**: Preserve existing response-model fields, lifecycle state,
  state digests, recorded-value booleans, pagination, and audit identifiers.
- **Rollback**: Revert E-1065 code, tests, this ADR, the manifest entry, and
  execution metadata together; do not restore direct identity serialization.
