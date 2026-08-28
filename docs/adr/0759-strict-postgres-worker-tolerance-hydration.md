# ADR 0759: Strict PostgreSQL worker tolerance hydration

- **Status**: Accepted
- **Date**: 2026-08-28
- **Context**: The PostgreSQL grouped and sequential worker adapters rejected
  binary floats but still normalized `amount_tolerance` with ad-hoc
  `Decimal(str(value))` logic. This left their rule boundary different from the
  platform strict financial parser and could accept representations such as
  scientific-notation text that the core financial contract deliberately
  refuses.
- **Decision**: Parse grouped and sequential worker `amount_tolerance` values
  with `parse_exact_amount()`, reject negative values, and serialize the
  accepted Decimal as canonical non-scientific text. Preserve the existing
  public error wording and the explicit supported-mode checks.
- **Rationale**: A worker must apply the same versioned financial-input policy
  before it constructs a strategy request. Tolerance values affect candidate
  selection and therefore are part of the reproducible financial decision.
- **Compatibility**: Exact text, integers, and Decimal values retain their
  behavior and canonical output. Binary floats, malformed values, and
  scientific-notation text now fail at the adapter boundary with the existing
  safe validation messages.
- **Verification**: Grouped and sequential worker tests cover binary-float and
  noncanonical tolerance refusal plus existing projection/digest behavior.
  Full regression, static/security gates, package build, YAML, and diff checks
  are recorded in the execution evidence.
- **Rollback**: Revert E-1099, ADR 0759, the worker/test changes, manifest
  entry, and execution records together.
