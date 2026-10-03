# ADR 0731: Local Workflow Responses Use Fail-Closed Projection

- **Date**: 2026-08-27
- **Status**: Accepted
- **Context**: Local workflow routes serialized state-machine models directly
  with `model_dump`, allowing future model fields to change the API response
  without a reviewed boundary contract.
- **Decision**: Apply central projections to workflow objects, allowed
  transitions, and history events. Invalid model response shapes fail closed
  with a bounded API error.
- **Verification**: Field-access tests inject future object, transition, and
  event fields; workflow API/state-machine/schema suites pass. Full regression
  and release gates are recorded before closure.
- **Compatibility**: Preserve the existing object lifecycle, transition
  permissions, SoD metadata, and history audit fields.
- **Rollback**: Revert E-1071 code, tests, this ADR, the manifest entry, and
  execution metadata together; do not restore direct workflow serialization.
