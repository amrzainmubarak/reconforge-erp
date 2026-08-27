# ADR 0706: Master Data Summary API Uses Fail-Closed Field Projection

- **Date**: 2026-08-27
- **Status**: Accepted
- **Context**: The master-data summary endpoint exposes organization, legal
  entity, branch, period, currency, source, and unsupported-collection counts.
  The local service summary was serialized directly, creating a disclosure
  boundary different from the manually bounded PostgreSQL branch.
- **Decision**: Use one central summary allowlist for both local SQLite and
  tenant-scoped PostgreSQL responses. Unknown future fields are dropped before
  serialization; the existing known count and source fields remain compatible.
- **Verification**: `tests/test_field_access.py` covers the summary allowlist,
  and `tests/test_api_master_data_projection.py` injects a future local
  service field through the route and proves it is absent. Focused and full
  release-quality gates are required for the evidence record.
- **Compatibility**: This is a response-disclosure change only. It does not
  alter master-data persistence, relationships, currency policy, lifecycle,
  authorization, or audit behavior.
- **Rollback**: Revert E-1046 code, tests, this ADR, the manifest entry, and
  execution metadata together. Do not restore unbounded summary serialization
  without a reviewed allowlist and regression coverage.
