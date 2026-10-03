# ADR 0684: Account reconciliation API uses fail-closed field projection

- **Status:** Accepted
- **Date:** 2026-08-26
- **Decision owners:** ReconForge execution slice

## Context

The account reconciliation SQLite and PostgreSQL repositories use broad reads
for records and reconciliation items. The API returned these mappings directly
for list, read, create, and lifecycle operations. A future storage or adapter
field could therefore become an API field without a reviewed contract change.

## Decision

Apply one central, fail-closed allowlist to all account reconciliation response
paths. Project nested reconciliation items with a separate allowlist and drop
unknown fields before serialization. Preserve the reviewed local/PostgreSQL
fields and existing response envelopes.

## Consequences

- Schema growth cannot silently expand the account reconciliation API.
- Local SQLite and PostgreSQL responses share one reviewed disclosure boundary.
- Nested item records cannot bypass the top-level response contract.
- Future contract fields require an explicit allowlist and regression test.
- This is a bounded disclosure control, not universal field-level
  authorization, external IAM, distributed revocation, disclosure approval,
  source authenticity, or production authorization effectiveness.

## Verification and boundary

`tests/test_field_access.py` covers unknown record and item fields.
`tests/test_api_accounts.py` covers an unknown server adapter field.
`tests/test_api_platform_routes.py` adds synthetic future columns to local
account tables and proves that the fields do not reach API responses. Full
Python regression, Ruff, Mypy, Bandit, pip-audit, package build, YAML, and diff
checks are required for closure. PostgreSQL live production effectiveness is
not implied.

## Rollback

Revert E-1024 code/tests/ADR 0684/manifest and execution metadata together.
Do not restore direct mapping serialization.
