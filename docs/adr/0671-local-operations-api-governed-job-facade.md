# ADR 0671: Route local durable-job queue health through the governed facade

- **Status**: Accepted
- **Date**: 2026-08-26
- **Related execution slice**: E-1011
- **Scope**: local SQLite `/api/v1/ops/durable-jobs/queue` route

## Context

The local operations route already required `ops.read`, but after that
dependency it called `DurableJobApplicationService.queue_snapshot` directly.
That left the route outside the exact object/scope binding introduced by ADR
0670. The Server Profile has a separate PostgreSQL identity and tenant-audit
boundary and must not be made to use a local SQLite authorization context.

## Decision

In local mode, build a request-scoped `PolicyEvaluationContext` from the
authenticated local user and the selected tenant/workspace/organization/entity
query scope. Resolve the user's local permissions from the same database and
call `GovernedDurableJobApplicationService.queue_snapshot` with `ops.read`,
the authenticated actor ID, and the request ID. The response schema and
sanitized projection remain unchanged.

Server mode was intentionally left on its existing
`enforce_server_tenant_permission` and PostgreSQL RLS boundary in this local
slice. E-1012 subsequently adds the verified `ServerPrincipal` to the same
governed facade while retaining those server-specific barriers.

## Consequences and boundaries

The local queue-health path now has defense in depth: the route dependency
checks authentication/permission and the application facade rechecks the
selected hierarchy before repository access. This does not prove universal API
adoption, external IAM, distributed revocation, PostgreSQL policy-audit sink
parity, HA/DR, production SLOs, or production readiness.

## Verification

- `python -m pytest -q tests/test_api_operations.py`
- `python -m pytest -q tests/test_api_operations.py tests/test_governed_jobs_policy.py tests/test_governed_worker_policy.py`
- `python -m ruff check reconforge/api/routes/operations.py tests/test_api_operations.py`
- `python -m mypy reconforge/api/routes/operations.py reconforge/application/jobs.py`

## Rollback

Revert E-1011 route/test/manifest/ADR/execution-document changes. No schema,
migration, external provider, or user data is changed.
