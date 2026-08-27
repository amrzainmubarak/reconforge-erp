# ADR 0708: Consolidation Close Summary API Uses Fail-Closed Field Projection

- **Date**: 2026-08-27
- **Status**: Accepted
- **Context**: The consolidation-close summary endpoint exposes lifecycle
  counts for periods, locks, runs, and reversals through local SQLite and
  tenant-scoped PostgreSQL repositories. The underlying typed summary was
  serialized directly, leaving a future-field disclosure gap in an otherwise
  projected API family.
- **Decision**: Apply the central consolidation summary allowlist to both
  backend branches before serialization. Preserve the declared lifecycle
  counts and drop unknown fields.
- **Verification**: `tests/test_field_access.py` covers every declared count
  and synthetic future fields. The consolidation API server-boundary test
  injects a future field through the PostgreSQL-shaped summary and proves it
  is absent. Focused and full release-quality gates are required for the
  evidence record.
- **Compatibility**: This changes response disclosure only. It does not alter
  period locking, run lifecycle, reversal controls, scope enforcement, or
  persistence.
- **Rollback**: Revert E-1048 code, tests, this ADR, the manifest entry, and
  execution metadata together. Do not restore direct summary serialization
  without a reviewed allowlist.
