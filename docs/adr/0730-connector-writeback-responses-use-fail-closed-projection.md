# ADR 0730: Connector Write-Back Responses Use Fail-Closed Projection

- **Date**: 2026-08-27
- **Status**: Accepted
- **Context**: Several connector write-back routes serialized immutable intent
  and recovery models directly with `model_dump`, making response shape depend
  on future model additions rather than a reviewed API contract.
- **Decision**: Apply central nested projections to every write-back intent
  response and recovery-observation list response across local and server
  paths. Malformed nested contracts fail closed with bounded API errors.
- **Verification**: Field-access tests inject future fields into intent,
  approval, acknowledgement, recovery-record, and provider-observation
  boundaries; connector API and observation suites pass. Full regression and
  release gates are recorded before closure.
- **Compatibility**: Preserve the existing lifecycle, identity, digest,
  approval, acknowledgement, compensation, and recovery-observation fields.
- **Rollback**: Revert E-1070 code, tests, this ADR, the manifest entry, and
  execution metadata together; do not restore direct model serialization.
