# ADR 0681: Close API uses fail-closed field projection

- **Status:** Accepted
- **Date:** 2026-08-26
- **Decision owners:** ReconForge execution slice

## Context

The local close repository used `SELECT *` for period and task reads. The
close routes also returned local and PostgreSQL adapter mappings directly.
That made a future storage column or adapter field part of the API response
without an explicit contract review. Close data is an authorized control
surface, but authorization alone does not make an evolving response safe.

## Decision

Apply one central, fail-closed field projection to all `/api/v1/close`
period, task, and readiness responses. The allowlists intentionally cover the
union of the existing SQLite and PostgreSQL response shapes. Unknown fields
are dropped before serialization. Existing field names and route permissions
remain unchanged; the projection does not add sensitive-field approval or
claim universal field-level authorization.

## Consequences

- SQLite schema growth cannot silently expand the close API response.
- Local and PostgreSQL adapters share one reviewed response contract.
- The response remains backward-compatible for currently published fields.
- Projection metadata is retained internally by the common primitive for
  deterministic tests; the close API does not add a new response envelope.
- This is a bounded disclosure control, not evidence of external IAM,
  distributed revocation, production authorization effectiveness, or
  statutory close control in a source ERP.

## Verification and boundary

`tests/test_field_access.py` covers all three close record shapes and unknown
field denial. `tests/test_api_platform_routes.py` adds future SQLite columns
to both close tables and proves that period, task, and readiness responses do
not expose them. Focused tests, Ruff, Mypy, full Python regression, package
build, YAML, and diff checks are required for closure.

## Rollback

Revert E-1021 code/tests/ADR 0681 and execution metadata together. Do not
restore direct `SELECT *`-backed API serialization as a compatibility measure.
