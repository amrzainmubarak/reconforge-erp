# ADR 0756: Matching input persistence follows the financial input policy

- **Status**: Accepted
- **Date**: 2026-08-28
- **Context**: The PostgreSQL matching adapter passed a financial input policy to
  the deterministic engine, but `_register_inputs()` independently converted
  source amounts with `Decimal(str(value))`. A binary float could therefore be
  represented as an apparently exact persisted amount even though the selected
  strict policy rejected it in the engine.
- **Decision**: Route source-amount hydration in `_register_inputs()` through
  `parse_amount(input_policy=...)`, and pass the same policy used by the engine
  from both source sides. Under the strict policy, binary floating-point,
  malformed, non-finite, and missing amounts remain `None` and make the input
  invalid. The explicit legacy policy retains its compatibility conversion.
- **Rationale**: The amount used by matching and the amount recorded in the
  evidence graph must be governed by one versioned policy. Invalid financial
  input must never become a usable amount through a persistence-only conversion.
- **Compatibility**: Exact text, integer, Decimal, and existing valid legacy
  inputs retain their persisted behavior. Only strict binary-floating-point
  source hydration changes from an apparently valid Decimal to invalid input.
- **Verification**: The PostgreSQL matching application tests cover strict
  rejection, legacy compatibility, source lineage, and the existing complete
  run. Ruff, Mypy, full regression, security/dependency gates, package build,
  YAML, and diff checks are recorded in the execution evidence.
- **Rollback**: Revert E-1096, ADR 0756, the manifest entry, adapter/test
  changes, and execution records together.
