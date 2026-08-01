# ADR 0135: PostgreSQL control-testing contract parity

- Status: Accepted
- Date: 2026-07-28

## Context

The control-testing application boundary supports library import, test
planning, result recording, remediation, reporting, and plan reads. SQLite
already preserves the plan workspace when creating an ineffective-result
exception. A PostgreSQL implementation must preserve that full behavior under
tenant isolation rather than merely reproduce primary rows.

## Decision

Add migration 0017 with tenant-keyed control library, test plan, test result,
and remediation tables. Enable and force RLS on every new table. Bind the
adapter to one validated tenant and set transaction-local tenant scope for
every operation. Keep each mutation, its unified exception when applicable,
its audit-chain event, and its outbox event in the same transaction.

Preserve the caller-supplied effectiveness value in audit metadata while the
stored result uses its normalized value, matching the SQLite evidence contract.
Package the Alembic assets and the shared `reconforge_migration_sql` loader so
installed revisions can resolve their schema SQL outside a source checkout.

The existing shared `control_exceptions` table from migration 0016 remains the
single queue surface. Result exceptions inherit the immutable plan workspace
and control metadata. No server operation silently creates a workspace.

## Consequences

The application contract now has both SQLite and PostgreSQL adapters, an
additive migration, local failure tests, and optional live non-superuser parity
coverage. Deployments must apply migrations in order and grant the application
role access without table ownership, superuser, or BYPASSRLS privileges.

A synthetic post-write Outbox failure is required to prove transaction rollback,
and an isolated wheel installation is required to import revision 0017.

Live RLS and runtime parity are not claimed until the optional service test
runs against that operational role. Downgrade removes only the four new tables;
it does not modify SQLite or the public service contract.
