# ADR 0633: Expose Account Reconciliation through the PostgreSQL server boundary

- Status: Accepted
- Date: 2026-08-26
- Scope: `reconforge.api.routes.accounts`

## Context

The Account Reconciliation PostgreSQL aggregate already had a tenant-scoped
repository, forced RLS schema, lifecycle guards, append-only transition
evidence, and exact decimal serialization. The HTTP router, however, was
SQLite-only and used the generic local database dependency. In a PostgreSQL
server profile that left an unsafe ambiguity: a request could authenticate as
a server principal while reading or mutating a tenant-local SQLite database.

## Decision

Add an explicit server capability boundary for the seven Account
Reconciliation routes. When the PostgreSQL server profile is configured, the
routes:

- resolve tenant/workspace/organization/entity from the authenticated request
  execution scope;
- re-evaluate the central policy against that scope before repository access;
- open a short `PostgresTenantBoundary` transaction with the same hierarchy;
- use `PostgresAccountReconciliationRepository` rather than SQLite;
- bind create, prepare, review, and complete actors to the authenticated
  principal; and
- ignore client-supplied preparer/reviewer identity in server mode.

Local mode keeps the existing SQLite service and compatibility contract. The
server boundary is covered by a capability-gated live FastAPI test using the
digest-pinned PostgreSQL 16 Alpine image and a `NOBYPASSRLS` non-superuser
role.

## Consequences and limits

The account route no longer has a silent SQLite fallback in server mode. The
live gate proves one-host synthetic HTTP lifecycle, exact decimal output,
maker-checker actor separation, forced workspace scope, and PostgreSQL RLS
execution. It does not prove external IAM authenticity, HA/DR, multi-host
failure behavior, provider integration, capacity, or production readiness.

## Rollback

Revert the server route, adapter boundary, test, and documentation together.
Do not restore generic SQLite access in PostgreSQL server mode; if the server
adapter is withdrawn, replace it with an explicit fail-closed response until
an equivalent scoped implementation is available.
