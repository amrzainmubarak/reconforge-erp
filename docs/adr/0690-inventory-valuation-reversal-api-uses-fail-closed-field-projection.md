# ADR 0690: Inventory Valuation Reversal API uses fail-closed field projection

- **Status:** Accepted
- **Date:** 2026-08-26
- **Decision owners:** ReconForge execution slice

## Context

Valuation-reversal routes returned local SQLite and PostgreSQL mappings. Their
effect records contain restoration/removal quantities and values, while
summary and snapshot responses aggregate the financial evidence. Broad row
reads or adapter changes could silently expose future fields across these
responses.

## Decision

Apply central allowlists to reversal and summary responses, an independent
allowlist to effect records, and a recursive closed projection to snapshot
source, summary, and reversal collections. Reject malformed nested
collections or records before serialization.

## Consequences

- Future storage or adapter fields cannot silently expand the reviewed
  valuation-reversal API response family.
- Restore/remove effect fields remain explicit and cannot bypass the parent
  reversal contract.
- Local SQLite and PostgreSQL shapes share one reviewed response contract.
- Future contract fields require an explicit allowlist and regression test.
- This is a bounded disclosure control, not universal field-level
  authorization, external IAM, distributed revocation, disclosure approval,
  source authenticity, or production authorization effectiveness.

## Verification and boundary

`tests/test_field_access.py` covers unknown reversal, effect, summary, and
snapshot fields. `tests/test_inventory_valuation_reversal.py` adds synthetic
future columns to reversal/effect tables and verifies create, approve, list,
and snapshot HTTP responses omit them. Focused tests and the full Python
regression pass at 100%; Ruff, Mypy (539 source files), Bandit, pip-audit,
package build, targeted YAML validation (9 files), and diff checks also pass.
This ADR does not cover unrelated inventory or financial routes.

## Rollback

Revert E-1030 code/tests/ADR 0690/manifest and execution metadata together.
Do not restore direct repository-row serialization.
