# ADR 0672: Use the governed durable-job facade in Server Profile queue health

- **Status**: Accepted
- **Date**: 2026-08-26
- **Related execution slice**: E-1012
- **Scope**: PostgreSQL Server Profile `/api/v1/ops/durable-jobs/queue` route

## Context

E-1011 moved the local SQLite queue-health route to the governed application
facade. The Server Profile still called the raw application service after its
tenant permission check and before its PostgreSQL RLS transaction. That left
the two deployment modes with different application-layer object/scope
binding.

## Decision

The Server Profile now builds a `PolicyEvaluationContext` from the verified
`ServerPrincipal`, selected hierarchy, and principal scope grants, then calls
`GovernedDurableJobApplicationService.queue_snapshot` with the authenticated
principal and request ID. Existing `enforce_server_tenant_permission`,
transaction-local PostgreSQL scope, and RLS enforcement remain in place as
independent barriers. The route response and backend repository contract do
not change.

The facade's provider-neutral structured policy evidence is injectable;
E-1013 wires it to the same server request's PostgreSQL policy-audit sink. The
route-level server recheck continues to use that sink as an independent
barrier.

## Consequences and boundaries

Both local and Server Profile queue-health paths now use the governed
application facade. This does not prove every API route is governed, external
IAM or distributed revocation, provider interoperability, independent
production audit assurance, HA/DR, production SLOs, or production readiness.

## Verification

- `python -m pytest -q tests/test_api_operations.py`
- `python -m ruff check reconforge/api/routes/operations.py tests/test_api_operations.py`
- `python -m mypy reconforge/api/routes/operations.py reconforge/application/jobs.py`

## Rollback

Revert E-1012 route/test/manifest/ADR/execution-document changes. No schema,
migration, external provider, or user data is changed.
