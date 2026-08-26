# ADR 0689: Inventory Valuation policy, layer, and snapshot API uses fail-closed field projection

- **Status:** Accepted
- **Date:** 2026-08-26
- **Decision owners:** ReconForge execution slice

## Context

Inventory Valuation policy and cost-layer routes returned local SQLite and
PostgreSQL adapter mappings. The summary and snapshot aggregate those
records, including financial money/quantity values and nested collections.
Broad repository reads or adapter changes could otherwise silently expose
future fields across several financial response paths.

## Decision

Apply central allowlists to policy, cost-layer, and summary responses. Apply a
recursive closed projection to snapshot source, summary, policies, documents,
and open cost layers. Reject malformed nested collections or records before
serialization.

## Consequences

- Future storage or adapter fields cannot silently expand the reviewed
  Inventory Valuation policy, layer, summary, and snapshot API responses.
- Local SQLite and PostgreSQL shapes share explicit response contracts while
  retaining deliberate backend-specific identifiers.
- Snapshot aggregation cannot bypass the contracts already applied to nested
  document records.
- Future contract fields require an explicit allowlist and regression test.
- This is a bounded disclosure control, not universal field-level
  authorization, external IAM, distributed revocation, disclosure approval,
  source authenticity, or production authorization effectiveness.

## Verification and boundary

`tests/test_field_access.py` covers unknown policy, layer, and snapshot
fields. `tests/test_inventory_valuation.py` adds synthetic future columns to
the reviewed valuation tables and verifies policy, layer, document, and
snapshot HTTP responses omit them. Focused tests and the full Python
regression pass at 100%; Ruff, Mypy (539 source files), Bandit, pip-audit,
package build, targeted YAML validation (9 files), and diff checks also pass.
This ADR does not cover unrelated inventory or financial routes.

## Rollback

Revert E-1029 code/tests/ADR 0689/manifest and execution metadata together.
Do not restore direct repository-row serialization.
