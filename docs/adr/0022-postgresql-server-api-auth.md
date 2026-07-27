# ADR 0022: PostgreSQL Server API Authentication Profile

- Status: Accepted as a bounded transition profile
- Date: 2026-07-23
- Decision owners: ReconForge maintainers

## Context

The PostgreSQL identity repository provided tenant-scoped passwords, RBAC, and
sessions, but the FastAPI layer still authenticated only against SQLite. A
server deployment therefore lacked a verified principal path even though the
database boundary existed. The remaining domain services still use SQLite and
must not silently become shared or unscoped when server authentication is
enabled.

## Decision

Add an explicit `create_api_app(..., postgres_dsn=..., tenant_db_root=...)`
profile. It requires database-per-tenant SQLite routing for legacy domain
records and uses PostgreSQL/RLS for `/auth/login`, bearer validation,
permission snapshots, `/auth/me`, and logout. Middleware authenticates bearer
requests once and binds a `ServerPrincipal` across the entire route execution.
The principal is used by API dependencies and by domain authorization/audit
helpers, so legacy services do not fall back to a local `local-cli` label or a
different SQLite user.

The default local API profile remains unchanged. The server profile is opt-in,
requires a tenant header for identity operations, and fails closed on missing
or invalid tenant scope. It is not presented as full hosted PostgreSQL
persistence, enterprise federation, MFA, or multi-worker Redis coordination.

## Consequences

- API authentication and current domain principal attribution are backed by a
  real tenant-scoped PostgreSQL identity boundary.
- Cross-tenant bearer tokens fail through PostgreSQL RLS and tenant-scoped
  queries; the legacy domain database is separately isolated by the router.
- Existing local deployments retain SQLite sessions and trusted-local CLI
  compatibility.
- Domain migration remains required before the server profile can claim shared
  PostgreSQL persistence; user/role administration routes remain a future
  server identity-management slice.

## Rejected alternatives

- Trusting `X-ReconForge-Tenant` without a tenant-scoped token lookup: a header
  is scope input, not proof of identity.
- Keeping SQLite auth while exposing PostgreSQL financial repositories: the
  server would have split identity authority and unsafe principal attribution.
- Binding a principal only inside one dependency: sibling dependencies and
  synchronous domain handlers could lose the authorization context.
