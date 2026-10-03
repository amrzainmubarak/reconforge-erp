# ADR 0718: Consolidation Evidence Links Use Fail-Closed Projection

- **Date**: 2026-08-27
- **Status**: Accepted
- **Context**: Five PostgreSQL consolidation-close evidence-link mutations
  returned raw link rows. The link tables share a common identity/digest shape
  but include type-specific fields, so future adapter columns could escape the
  API boundary inconsistently.
- **Decision**: Apply one central compatibility-union projection to all five
  link responses and independently project the source envelope. Preserve
  identity, artifact/run binding, digest, type-specific evidence fields, actor,
  and creation metadata.
- **Verification**: A server-shaped intercompany route test injects an unknown
  link field and proves it is absent while the common and type-specific fields
  remain available. The existing close-link suites continue to cover lifecycle
  and evidence binding behavior.
- **Compatibility**: No evidence-link state, digest, or binding behavior
  changes; only unknown response fields are removed.
- **Rollback**: Revert E-1058 code, tests, this ADR, the manifest entry, and
  execution metadata together; do not restore direct link-row serialization.
