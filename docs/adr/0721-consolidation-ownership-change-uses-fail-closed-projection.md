# ADR 0721: Consolidation Ownership-Change Uses Fail-Closed Projection

- **Date**: 2026-08-27
- **Status**: Accepted
- **Context**: The authenticated Consolidation Ownership-Change prepare and
  read routes returned PostgreSQL artifact dictionaries directly. The
  persisted contract contains request/result JSON, exact Money values, and
  balanced adjustment lines; future adapter or payload fields could cross
  the API boundary without review.
- **Decision**: Apply one central projection to the artifact and source
  envelope. Project request/result payloads, canonical Money values, and
  adjustment lines through closed compatibility unions. Reject malformed
  nested shapes rather than silently serializing them.
- **Verification**: Focused API and field-access tests inject future fields at
  artifact, payload, Money, line, source, and envelope levels. Existing
  ownership-change deterministic and persistence contract tests remain part
  of the full regression gate.
- **Compatibility**: Preserve reviewed request/result lineage, exact-money
  metadata, percentages, approval, balanced lines, and non-posting status.
  Unknown fields are removed.
- **Rollback**: Revert E-1061 code, tests, this ADR, the manifest entry, and
  execution metadata together; do not restore direct artifact serialization.
