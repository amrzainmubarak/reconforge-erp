# ADR 0021: PostgreSQL Identity, RBAC, and Hashed Sessions

- Status: Accepted as a bounded server slice
- Date: 2026-07-23
- Decision owners: ReconForge maintainers

## Context

The PostgreSQL server boundary had tenant-aware reference and ledger data, but
no tenant-scoped principal store. A hosted API cannot safely authorize ledger
or control operations from a caller-supplied tenant label or an unhashed
session token. The local SQLite identity model remains useful for local mode,
but it is not a server persistence boundary.

## Decision

Add Alembic revision `0004_postgres_identity` and
`PostgresIdentityRepository`. The schema stores tenant-scoped users, roles,
permissions, role assignments, and sessions. Passwords use the existing
PBKDF2-SHA256 password-hash format; bearer tokens are generated once and only
their SHA-256 digests are stored. User authentication uses row locking,
failed-login counters, and a bounded lockout interval. Token authentication
checks tenant scope, expiry, revocation, and disabled users, with throttled
last-use updates. Repository methods use parameterized SQL and caller-owned
transactions.

All identity tables enable and force PostgreSQL row-level security and use
composite tenant-aware foreign keys. The repository therefore provides a real
server identity persistence boundary, but it does not claim enterprise
federation, MFA, or API integration until authenticated principals are wired
through every server route and worker.

## Consequences

- Password verification, RBAC assignment, session hashing, lockout, and
  revocation have a tenant-scoped PostgreSQL implementation.
- Direct database access by a non-privileged application role is covered by
  live RLS and cross-tenant visibility tests.
- Raw bearer tokens are not recoverable from the database after creation.
- The existing API and Studio continue to use their local authentication path;
  this repository is opt-in server infrastructure until principal propagation
  is implemented.
- OIDC, SAML, SCIM, MFA, password reset, secret rotation, and full lifecycle
  administration remain future bounded contexts.

## Rejected alternatives

- Storing raw session tokens: a database disclosure would immediately become
  an active-session disclosure.
- Trusting tenant headers as identity: tenant scope must be bound by the
  transaction and authenticated principal, then enforced by RLS.
- Reusing the local SQLite session database for hosted workers: it cannot
  provide the required shared, tenant-scoped, multi-process boundary.
