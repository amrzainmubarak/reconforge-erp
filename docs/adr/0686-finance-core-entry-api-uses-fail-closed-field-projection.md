# ADR 0686: Finance Core entry API uses fail-closed field projection

- **Status:** Accepted
- **Date:** 2026-08-26
- **Decision owners:** ReconForge execution slice

## Context

Finance Core entry routes returned mappings from three bounded persistence
shapes: local SQLite Finance Core, PostgreSQL Finance Core, and the legacy
tenant-scoped PostgreSQL ledger. Some local queries use `SELECT *`, and future
adapter fields or nested ledger-line changes could therefore become API output
without a reviewed response-contract change.

## Decision

Apply central, fail-closed allowlists to Finance Core ledger-entry list, read,
create, validate, and void responses. Project nested ledger lines through a
separate reviewed allowlist. Keep the existing response envelopes and known
financial fields compatible while denying unknown top-level and nested fields.

## Consequences

- Future storage or adapter fields cannot silently expand the ledger-entry API.
- Local and server adapters share one explicit response boundary despite
  differing physical column names.
- Existing permissions, tenant/workspace checks, and financial write rules are
  unchanged.
- Future contract fields require an explicit allowlist and regression test.
- This is a bounded disclosure control, not universal field-level
  authorization, external IAM, distributed revocation, disclosure approval,
  source authenticity, or production authorization effectiveness.

## Verification and boundary

`tests/test_field_access.py` covers unknown entry and nested line fields.
`tests/test_api_server_finance_core.py` covers route-level projection.
Focused and full regression, Ruff, Mypy, Bandit, pip-audit, package build,
YAML, and diff gates are required for closure. Live production IAM
effectiveness is not implied.

## Rollback

Revert E-1026 code/tests/ADR 0686/manifest and execution metadata together.
Do not restore direct repository-mapping serialization.
