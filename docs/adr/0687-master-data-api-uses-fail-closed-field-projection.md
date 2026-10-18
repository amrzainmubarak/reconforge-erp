# ADR 0687: Master Data API uses fail-closed field projection

- **Status:** Accepted
- **Date:** 2026-08-26
- **Decision owners:** ReconForge execution slice

## Context

Master Data routes returned local SQLite `SELECT *` rows and PostgreSQL
adapter mappings for currencies, organizations, legal entities, branches, and
fiscal periods. The versioned snapshot also carried those collections and a
nested currency-registry reconciliation result. Future storage or adapter
fields could therefore become API output without a reviewed contract change.

## Decision

Apply explicit central allowlists to every reviewed Master Data resource list
and mutation response. Apply a closed recursive projection to the versioned
snapshot, including its source, summary, resource collections, and
currency-registry nested records. Reject malformed nested records before
serialization.

## Consequences

- Future Master Data storage or adapter fields cannot silently expand the API.
- Local and server response shapes remain compatible through one reviewed
  contract per resource.
- Scope-defining identifiers and period/currency metadata remain available to
  authorized consumers.
- Future contract fields require an explicit allowlist and regression test.
- This is a bounded disclosure control, not universal field-level
  authorization, external IAM, distributed revocation, disclosure approval,
  source authenticity, or production authorization effectiveness.

## Verification and boundary

`tests/test_field_access.py` covers unknown snapshot and nested resource
fields. `tests/test_master_data.py` adds synthetic future columns to all five
local Master Data tables and verifies list/snapshot responses. Full regression,
Ruff, Mypy, Bandit, pip-audit, package build, targeted YAML, and diff gates
are required for closure. Live production IAM effectiveness is not implied.

## Rollback

Revert E-1027 code/tests/ADR 0687/manifest and execution metadata together.
Do not restore direct repository-row serialization.
