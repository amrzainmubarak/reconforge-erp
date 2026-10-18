# ADR 0760: Strict PostgreSQL database-connector amount hydration

- **Status**: Accepted
- **Date**: 2026-08-28
- **Context**: The read-only PostgreSQL named-query connector rejected Python
  floats, but otherwise parsed amounts with direct `Decimal(str(value))` logic.
  Its numeric boundary therefore differed from the platform strict financial
  parser and accepted some representations that the core contract rejects.
- **Decision**: Use `parse_exact_amount()` in the PostgreSQL connector's
  canonical amount reader. Preserve the existing safe error categories for
  binary-float type, non-finite Decimal, and general malformed values, then
  serialize the accepted value through the existing canonical decimal writer.
- **Rationale**: A database connector is an untrusted adapter boundary. Its
  amount must obey the same exact-input and deterministic serialization policy
  before entering `DatabaseRecordRow` and downstream reconciliation.
- **Compatibility**: Exact decimal text, integers, and finite Decimal values
  retain their canonical output. Existing public connector error codes remain
  stable; binary floats, booleans, malformed values, and disallowed
  representations fail closed.
- **Verification**: PostgreSQL connector tests cover normal read-only transport
  behavior and strict hydration refusal for binary float, scientific text,
  boolean, and non-finite Decimal inputs. Full regression, static/security
  gates, package build, YAML, and diff checks are recorded in E-1100.
- **Rollback**: Revert E-1100, ADR 0760, connector/test changes, manifest
  entry, and execution records together.
