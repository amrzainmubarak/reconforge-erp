# ADR 0728: Access Policy-Analysis Responses Use Fail-Closed Projection

- **Date**: 2026-08-27
- **Status**: Accepted
- **Context**: The access policy-analysis route returned `result.to_dict()`
  directly. Its deterministic result contains conflict findings and digest
  metadata that must remain bounded at the authenticated API boundary.
- **Decision**: Apply a central recursive projection to policy-analysis result
  fields and conflict findings. Malformed finding collections fail closed with
  a bounded API error; fields outside the reviewed finding contract are not
  admitted.
- **Verification**: Field-access and authenticated route tests inject future
  result and finding fields and prove they do not escape. Full regression and
  release gates are recorded before closure.
- **Compatibility**: Preserve algorithm version, policy identifiers, digests,
  status, counts, and explainable finding fields.
- **Rollback**: Revert E-1068 code, tests, this ADR, the manifest entry, and
  execution metadata together; do not restore direct policy-analysis
  serialization.
