# ADR 0683: Consolidation-close API uses fail-closed field projection

- **Status:** Accepted
- **Date:** 2026-08-26
- **Decision owners:** ReconForge execution slice

## Context

The consolidation-close SQLite and PostgreSQL repositories use broad reads for
periods, runs, journal lines, effects, and effect lines. Their API routes
returned mappings directly, while the verified run response also contained
nested journal/effect data and reviewed PostgreSQL evidence arrays. A future
storage or adapter field could therefore become an API field without a reviewed
contract change.

## Decision

Apply central, fail-closed allowlists to every consolidation-close period and
run response path. Project journal lines, effect records, and effect lines
independently. Keep the reviewed PostgreSQL evidence fields explicit, while
excluding internal worksheet payload/cache fields and unknown adapter/storage
fields before serialization.

## Consequences

- Schema growth cannot silently expand the consolidation-close API response.
- Local SQLite and PostgreSQL response paths share one reviewed disclosure
  boundary.
- Existing known fields and response envelopes remain compatible.
- Future contract fields require an explicit allowlist and regression test.
- This is a bounded disclosure control, not universal field-level
  authorization, external IAM, distributed revocation, disclosure approval,
  source authenticity, or production authorization effectiveness.

## Verification and boundary

`tests/test_field_access.py` covers unknown top-level and nested fields.
`tests/test_api_consolidation_close.py` adds synthetic future columns to the
period, run, and run-line SQLite tables and proves that neither the column nor
its value reaches period or run responses. Full Python regression, Ruff, Mypy,
Bandit, pip-audit, package build, YAML, and diff checks are required for
closure. PostgreSQL live production effectiveness is not implied.

## Rollback

Revert E-1023 code/tests/ADR 0683/manifest and execution metadata together.
Do not restore direct `SELECT *` response serialization.
