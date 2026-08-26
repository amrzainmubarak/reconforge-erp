# ADR 0688: Inventory Valuation document API uses fail-closed field projection

- **Status:** Accepted
- **Date:** 2026-08-26
- **Decision owners:** ReconForge execution slice

## Context

Inventory Valuation document routes returned local SQLite and PostgreSQL
adapter mappings. Document detail responses also contained input-cost,
valuation-line, and layer-consumption collections. Because the underlying
repositories use broad row reads in parts of this path, a future storage or
adapter field could otherwise become financial API output without an explicit
contract review.

## Decision

Apply a central top-level allowlist to document list, create, read, approve,
and cancel responses. Apply independent child allowlists to input costs,
valuation lines, and layer consumptions. Reject malformed nested collections
or records before serialization.

## Consequences

- Future storage or adapter fields cannot silently expand the reviewed
  Inventory Valuation document API response family.
- Local SQLite and PostgreSQL shapes share one explicit response contract while
  retaining their deliberate backend-specific identifiers where needed.
- Money and quantity values remain the already formatted deterministic public
  fields; raw minor/scaled storage fields are not admitted by the projector.
- Future contract fields require an explicit allowlist and regression test.
- This is a bounded disclosure control, not universal field-level
  authorization, external IAM, distributed revocation, disclosure approval,
  source authenticity, or production authorization effectiveness.

## Verification and boundary

`tests/test_field_access.py` covers unknown document and nested financial
fields. `tests/test_inventory_valuation.py` adds synthetic future columns to
the valuation document tables and verifies list/detail HTTP responses omit
them. Focused tests and the full Python regression pass at 100%; Ruff, Mypy
(539 source files), Bandit, pip-audit, package build, targeted YAML validation
(9 files), and diff checks also pass. Policy, cost-layer, and snapshot
responses remain separate slices.

## Rollback

Revert E-1028 code/tests/ADR 0688/manifest and execution metadata together.
Do not restore direct repository-row serialization.
