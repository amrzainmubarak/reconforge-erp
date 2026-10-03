# ADR 0783: Migrate PostgreSQL metrics on clean boot

- Status: Accepted
- Date: 2026-10-03
- Owners: PostgreSQL / Evidence

## Context

Alembic head 0092 omitted metric definitions and snapshots. Existing adapter tests
installed their own tables and therefore did not detect that a fresh deployed
database could not compute the eight dashboard metrics.

## Decision

Add revision 0093 with frozen DDL and standard definitions. Definitions are shared
product metadata; snapshots carry tenant identity and forced row security.
Preserve existing custom definitions. Runtime roles receive read access to
definitions and ordinary scoped data access to snapshots through deployment grants.

## Verification and rollback

The live migration regression starts at 0092, upgrades through Alembic, computes
eight metrics from a nonempty synthetic fixture and verifies tenant read/write
isolation. Empty downgrade/upgrade is supported. Downgrade takes exclusive locks
and refuses retained snapshots or custom definitions, including when forced RLS
would otherwise hide them from the migration owner. Restore a verified pre-upgrade
backup for populated rollback; never silently delete retained evidence.

This fixes schema provisioning. It does not prove that every dashboard has
workspace-level authorization, nor complete financial reporting.
