# ADR 0685: Reconciliation API uses fail-closed field projection

- **Status:** Accepted
- **Date:** 2026-08-26
- **Decision owners:** ReconForge execution slice

## Context

The PostgreSQL reconciliation routes returned adapter mappings for run
metadata, cancellation/requeue results, and paginated canonical inputs,
deterministic results, and exceptions. A future adapter field or nested shape
change could therefore become API output without a reviewed response-contract
change.

## Decision

Apply central, fail-closed allowlists to reconciliation run, input, result, and
exception responses. Project nested run collections and each paginated child
collection through their own reviewed allowlist. Reject malformed child
collections before serialization.

## Consequences

- Future adapter fields cannot silently expand the reconciliation API.
- Nested child records cannot bypass their response contract.
- Existing known fields, envelopes, tenant scope, permissions, and actor
  binding remain compatible.
- Future contract fields require an explicit allowlist and regression test.
- This is a bounded disclosure control, not universal field-level
  authorization, external IAM, distributed revocation, disclosure approval,
  source authenticity, or production authorization effectiveness.

## Verification and boundary

`tests/test_field_access.py` covers unknown run and child fields.
`tests/test_api_server_reconciliation.py` covers unknown server adapter fields
across run and child responses. Full Python regression, Ruff, Mypy, Bandit,
pip-audit, package build, YAML, and diff checks are required for closure. Live
production IAM effectiveness is not implied.

## Rollback

Revert E-1025 code/tests/ADR 0685/manifest and execution metadata together.
Do not restore direct adapter mapping serialization.
