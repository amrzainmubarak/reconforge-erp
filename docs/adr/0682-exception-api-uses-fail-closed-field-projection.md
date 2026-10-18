# ADR 0682: Exception API uses fail-closed field projection

- **Status:** Accepted
- **Date:** 2026-08-26
- **Decision owners:** ReconForge execution slice

## Context

The local exception queue repository read `exceptions_queue` with `SELECT *`
and the API returned records directly for listing, assignment, and status
changes. A future SQLite column could therefore become an API field without a
reviewed response-contract change.

## Decision

Apply one central, fail-closed exception-record allowlist to all
`/api/v1/exceptions` response paths. Preserve the currently exposed record
fields and local RBAC boundaries, while dropping unknown storage fields before
serialization. This slice remains local-only because the existing route
explicitly refuses the PostgreSQL Server Profile.

## Consequences

- Schema growth in the local exception queue cannot silently expand the API.
- Read and mutation responses share one reviewed response contract.
- Existing field names and response envelopes remain compatible.
- This is a bounded disclosure control, not universal field-level
  authorization, external IAM, distributed revocation, or production
  authorization effectiveness.

## Verification and boundary

`tests/test_field_access.py` covers the closed exception projection.
`tests/test_api_platform_routes.py` adds a synthetic future column and proves
that list, assign, and status responses omit the column and its value. Full
Python regression, Ruff, Mypy, Bandit, pip-audit, package build, YAML, and
diff checks are required for closure.

## Rollback

Revert E-1022 code/tests/ADR 0682/manifest and execution metadata together.
Do not restore direct `SELECT *` response serialization.
