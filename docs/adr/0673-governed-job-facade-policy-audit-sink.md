# ADR 0673: Inject the policy-audit sink into governed durable-job facade

- **Status**: Accepted
- **Date**: 2026-08-26
- **Related execution slice**: E-1013
- **Scope**: governed durable-job application policy decisions

## Context

The governed durable-job facade produced closed structured policy evidence,
but its audit call did not accept a request-scoped persistence sink. Server
Profile already has a tenant-scoped PostgreSQL policy-audit sink used by its
route dependencies, so facade decisions would otherwise be observable in
logs but not persisted through the same server audit boundary.

## Decision

Add an optional provider-neutral `PolicyAuditSink` to
`GovernedDurableJobApplicationService`. The facade passes it to
`audit_policy_decision` for every application decision. Server Profile injects
the existing tenant-scoped PostgreSQL sink; Community/local callers omit it
and retain the existing structured-log behavior. The facade remains independent
of PostgreSQL, SQLite, network, and provider-specific code.

## Consequences and boundaries

Server Profile queue-health decisions now use the same PostgreSQL policy-audit
boundary as the route-level authorization recheck. A sink failure remains
fail-closed through the existing server audit adapter. This does not prove
universal route adoption, external IAM, distributed revocation, provider
interoperability, HA/DR, production SLOs, or production readiness.

## Verification

- `python -m pytest -q tests/test_api_operations.py`
- `python -m pytest -q tests/test_governed_jobs_policy.py tests/test_governed_worker_policy.py`
- `python -m ruff check reconforge/application/jobs.py reconforge/api/routes/operations.py tests/test_api_operations.py`
- `python -m mypy reconforge/application/jobs.py reconforge/api/routes/operations.py`
- `python -m pytest -q`

## Rollback

Revert E-1013 facade/route/test/manifest/execution-document changes. Local
SQLite/CLI callers continue to work because the sink argument is optional.
