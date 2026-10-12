# ADR 0723: Consolidation Source-Bound Artifacts Use Fail-Closed Projection

- **Date**: 2026-08-27
- **Status**: Accepted
- **Context**: The authenticated PostgreSQL APIs for Intercompany
  Elimination, Consolidation Impairment, and Acquisition Deferred Tax
  returned artifact dictionaries directly. Their JSON contains exact Money,
  source lines/items, resolutions, and replay digests; future adapter or
  payload fields could cross the API boundary without review.
- **Decision**: Apply central, family-specific projections to each artifact
  and source envelope. Recursively project canonical Money, input lines or
  units/items, result lines/resolutions, and nested intercompany proposals.
  Malformed nested shapes fail closed rather than being serialized.
- **Verification**: Authenticated server-shaped API tests inject unknown
  artifact fields. Field-access tests inject unknown fields at Money,
  source-line, unit/item, resolution, proposal, and source-envelope levels.
  Existing deterministic replay and persistence contract suites remain the
  compatibility gate.
- **Compatibility**: Preserve reviewed lineage, exact-money metadata,
  non-posting status, source bindings, resolution explanations, and result
  digests. Unknown fields are removed.
- **Rollback**: Revert E-1063 code, tests, this ADR, the manifest entry, and
  execution metadata together; do not restore direct artifact serialization.
