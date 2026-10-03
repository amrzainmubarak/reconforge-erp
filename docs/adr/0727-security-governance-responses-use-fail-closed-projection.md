# ADR 0727: Security Governance Responses Use Fail-Closed Projection

- **Date**: 2026-08-27
- **Status**: Accepted
- **Context**: Security Governance routes serialized integration,
  retention-policy, and evidence-retention dataclasses directly with
  `asdict(...)`. These authenticated responses describe credential counts,
  retention state, and security lifecycle metadata that must remain bounded.
- **Decision**: Apply central projections to integration and retention-policy
  records, paginated envelopes, disable/policy-change mutations, and
  evidence-retention applications. Invalid nested shapes fail closed with
  bounded API errors. Policy-analysis remains a separate contract.
- **Verification**: Field-access tests inject unknown fields at integration,
  retention-policy, pagination, nested mutation, and retention-result
  boundaries. Authenticated API tests inject future fields through the route
  serialization seam and prove they do not escape. Full regression and release
  gates are recorded before closure.
- **Compatibility**: Preserve reviewed security lifecycle fields, state
  digests, retention dates, credential counts, pagination, and audit IDs.
- **Rollback**: Revert E-1067 code, tests, this ADR, the manifest entry, and
  execution metadata together; do not restore direct security-response
  serialization.
