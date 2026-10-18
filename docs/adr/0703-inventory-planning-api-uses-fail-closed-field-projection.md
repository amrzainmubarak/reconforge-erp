# ADR 0703: Inventory Planning API Uses Fail-Closed Field Projection

- **Date**: 2026-08-27
- **Status**: Accepted
- **Context**: Inventory Planning responses expose physical-count sessions,
  count lines, reorder rules, deterministic reorder signals, and snapshots
  from local SQLite and tenant-scoped PostgreSQL adapters. These responses
  contain quantities, adjustment references, approval metadata, and operational
  risk signals. Future adapter or storage fields must not silently expand the
  control surface.
- **Decision**: Apply central allowlists to every reviewed Inventory Planning
  response: count-session lifecycle mutations and reads, count-session lists,
  reorder-rule mutations and lists, reorder signals, and snapshots. Project
  count lines, session summaries, source metadata, pagination, signal objects,
  and snapshot collections recursively. Preserve exact scaled quantities,
  approval metadata, workspace scope, and existing lifecycle behavior.
- **Verification**: `tests/test_field_access.py` covers session lines,
  session summaries, reorder rules, signals, and snapshots. The Inventory
  Planning server-route test injects synthetic future fields through the
  create/read/list/snapshot/rule/signal paths and proves they are absent.
  Focused selectors pass 37 tests plus 1 existing live-PostgreSQL skip. The
  full Python regression passes 100%; Ruff, Mypy across 539 source files,
  Bandit, pip-audit, package build, source YAML validation across 174 files,
  and diff checks also pass. pip-audit reports the local distribution as
  unauditable because it is not published on PyPI.
- **Compatibility**: No schema, migration, persistence, permission, or
  inventory lifecycle behavior changes. This is a bounded disclosure control,
  not universal field-level authorization.
- **Rollback**: Revert E-1043 code, tests, this ADR, manifest entry, and
  execution metadata together. Do not restore unbounded planning-row
  serialization without replacement allowlists and regression evidence.
