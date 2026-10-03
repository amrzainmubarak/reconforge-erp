# ADR 0722: Evidence-Link Responses Use Fail-Closed Projection

- **Date**: 2026-08-27
- **Status**: Accepted
- **Context**: The PostgreSQL evidence-link mutation route returned the
  repository link dictionary directly. The link is part of the evidence
  lineage boundary, so an adapter column could otherwise cross the API
  response without review.
- **Decision**: Project the link through the established evidence-link field
  allowlist and independently project the source envelope through the common
  source metadata allowlist. Keep the route fail-closed when either nested
  response shape is malformed.
- **Verification**: The authenticated server-shaped evidence API test injects
  an unknown link field and proves it is absent; field-access tests cover the
  link and source response shape. Full evidence and regression suites remain
  the compatibility gate.
- **Compatibility**: Preserve evidence identity, object binding, link type,
  tenant, and timestamp fields; remove unknown adapter fields.
- **Rollback**: Revert E-1062 code, tests, this ADR, the manifest entry, and
  execution metadata together; do not restore direct link serialization.
