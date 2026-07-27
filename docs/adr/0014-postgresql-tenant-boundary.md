# ADR 0014: Optional PostgreSQL Tenant Boundary

- Status: Accepted as a foundation; domain integration pending
- Date: 2026-07-23
- Decision owners: ReconForge maintainers

## Context

ReconForge is SQLite-first for local reconciliation and control workflows. A
future server deployment needs a real PostgreSQL boundary without making the
local installation depend on server infrastructure or making an unsupported
hosted-isolation claim.

## Decision

Add an optional `server` dependency group containing `psycopg[binary]` and keep
the driver lazy-loaded. `PostgresConnectionFactory` applies a connection
timeout, a PostgreSQL statement timeout, and `sslmode=verify-full` by default.
The DSN is excluded from the settings representation so it is not accidentally
included in logs or diagnostic output.

Every tenant-scoped operation must begin a transaction and set
`app.tenant_id` and `app.organization_id` with parameterized,
transaction-local `set_config` calls. The foundation schema enables and forces
row-level security for tenants, organizations, and memberships. Policies deny
rows when a request has no matching tenant setting.

The application database role must not own these tables, be a superuser, or
have `BYPASSRLS`. Schema installation and tenant bootstrap use a separate
migration/administration role. This is required because PostgreSQL owners and
privileged roles can otherwise bypass RLS.

## Consequences

- SQLite remains the supported local persistence backend.
- The PostgreSQL adapter is a genuine connection and isolation boundary rather
  than a label around SQLite.
- Existing domain repositories are not silently redirected to PostgreSQL; they
  must be migrated behind repository contracts with upgrade and parity tests.
- Redis, workers, object storage, search, identity providers, and hosted
  deployment controls remain separate P1/P4 work.
- An opt-in live test verifies cross-tenant visibility when
  `RECONFORGE_TEST_POSTGRES_DSN` points to a disposable PostgreSQL database.

## Rejected alternatives

- Using a process-global tenant variable: unsafe with concurrency and pooled
  connections.
- Interpolating tenant IDs into SQL: unnecessary injection and scope ambiguity
  risk.
- Calling this hosted-ready before repositories and operational roles are
  integrated: would overstate the implementation.
