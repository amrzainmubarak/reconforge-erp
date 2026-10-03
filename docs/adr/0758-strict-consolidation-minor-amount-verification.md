# ADR 0758: Strict consolidation minor-amount verification

- **Status**: Accepted
- **Date**: 2026-08-28
- **Context**: PostgreSQL consolidation-close replay compared persisted decimal
  amounts with minor-unit-derived expected amounts using `Decimal(str(value))`.
  A binary float returned by a database adapter could therefore be accepted as
  an exact journal/effect amount during worksheet or effect verification.
- **Decision**: Use `parse_exact_amount()` for both the persisted actual amount
  and the canonical expected amount in `_amount_matches_minor()`. Preserve the
  existing equality check against `Money.from_minor_units()` and fail closed on
  binary floating-point, malformed, missing, or non-finite values.
- **Rationale**: Minor-unit verification is a financial integrity boundary for
  consolidation journal and effect evidence. A replay verifier must reject an
  inexact adapter value even when its string rendering happens to equal the
  expected decimal.
- **Compatibility**: Canonical decimal text and other exact supported inputs
  retain their behavior. Only binary-floating-point actual values that were
  previously coerced now fail verification.
- **Verification**: Consolidation-close and SQLite close suites cover exact
  equality, mismatch, and binary-float refusal. Full regression, static/security
  gates, package build, YAML, and diff checks are recorded in the execution
  evidence.
- **Rollback**: Revert E-1098, ADR 0758, the verifier/test changes, manifest
  entry, and execution records together.
