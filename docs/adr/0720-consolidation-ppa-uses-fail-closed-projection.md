# ADR 0720: Consolidation PPA Uses Fail-Closed Projection

- **Date**: 2026-08-27
- **Status**: Accepted
- **Context**: The authenticated Consolidation PPA prepare and read routes
  returned PostgreSQL artifact dictionaries directly. Those artifacts contain
  request/result JSON, canonical Money values, valuation items, and a nested
  goodwill bridge; future adapter or payload fields could cross the API
  boundary without review.
- **Decision**: Apply one central projection to the artifact and its source
  envelope. Project request/result payloads, canonical Money objects, PPA
  items, bridge lines, and bridge metadata through closed compatibility
  unions. Reject malformed nested shapes rather than silently serializing
  them.
- **Verification**: Focused API and field-access tests inject future fields
  at artifact, payload, item, bridge, line, Money, source, and envelope
  levels. Existing PPA request validation and persistence contract tests
  remain part of the full regression gate.
- **Compatibility**: Preserve reviewed PPA lineage, exact-money metadata,
  non-posting status, approval, valuation, and bridge fields. Unknown fields
  are removed.
- **Rollback**: Revert E-1060 code, tests, this ADR, the manifest entry, and
  execution metadata together; do not restore direct artifact serialization.
