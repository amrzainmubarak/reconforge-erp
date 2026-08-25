# ADR 0640: Fail closed before SQLite on local user routes in Server Profile

- Status: Accepted
- Date: 2026-08-26
- Scope: `reconforge.api.routes.users`, `tests/test_api_server_local_boundaries.py`

## Context

The legacy `/users` API is intentionally disabled when PostgreSQL server
identity is active because `/admin/identity` is the authoritative server
identity surface. The route guard already returned a clear `409`, but the
routes depended on `get_db`, so FastAPI opened the tenant SQLite connection
before the guard ran. This was an avoidable local-persistence and resource
boundary violation.

## Decision

Use `get_local_db` for every local user endpoint and resolve the connection
through a helper that checks Server Profile first. Server requests therefore
reject before local SQLite is opened; Local Profile keeps the existing user
management behavior. Roles already followed this pattern and remains covered
by the same contract.

## Evidence and limits

The server-boundary contract exercises user list/create/update/disable/role
assignment/role removal/permission reads and role reads against an app with an
unreachable PostgreSQL DSN. Authorized read paths return
`local_identity_surface_disabled`; higher-risk mutations may be rejected even
earlier by the required step-up policy, and all responses remain fail-closed.
Local user/role compatibility tests continue to pass.

This does not implement PostgreSQL identity administration; that authority is
already provided by the separate server identity/access routes. It does not
claim external IAM, SSO, HA/DR, or production readiness.

## Rollback

Revert the dependency and helper change together with the contract test and
documentation. Do not restore `get_db` to Server Profile-disabled user routes.
