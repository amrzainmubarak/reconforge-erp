# ADR 0757: Strict ownership-percentage hydration

- **Status**: Accepted
- **Date**: 2026-08-28
- **Context**: PostgreSQL and SQLite consolidation ownership readers, and the
  PostgreSQL ownership-change replay reader, reconstructed percentages with
  `Decimal(str(value))`. A binary float returned by an adapter or decoded from
  persisted JSON could therefore enter effective-ownership, NCI, or adjustment
  calculations as if it were exact.
- **Decision**: Hydrate all persisted ownership percentages through
  `parse_exact_amount()`: direct ownership in both ownership repositories, and
  prior/new group ownership in the PostgreSQL ownership-change request reader.
  The existing domain bounds remain authoritative: direct ownership is greater
  than zero and at most one; ownership-change percentages are between zero and
  one. Invalid or binary-floating-point values fail closed at replay hydration.
- **Rationale**: Ownership ratios are financial inputs because they determine
  consolidation scope, NCI allocation, and proposed equity adjustments. The
  exact-input contract must hold at every persistence and replay boundary, not
  only at initial domain construction.
- **Compatibility**: Exact decimal text, integers, and Decimal values retain
  their behavior. Values already persisted as canonical decimal text are
  unchanged. Adapter or JSON binary floats that were previously coerced now
  fail closed instead of affecting financial calculations.
- **Verification**: PostgreSQL ownership, SQLite ownership, ownership-change,
  and domain regression tests cover the three hydration boundaries. Full
  regression, static/security gates, package build, YAML, and diff checks are
  recorded in the execution evidence.
- **Rollback**: Revert E-1097, ADR 0757, the changed readers/tests, manifest
  entry, and execution records together.
