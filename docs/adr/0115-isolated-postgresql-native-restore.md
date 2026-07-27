# ADR 0115: Isolated PostgreSQL native restore

- Status: Accepted
- Date: 2026-07-27

## Context

PostgreSQL recovery cannot safely reuse the SQLite logical-row format. Native
tools preserve database objects and transactional dump semantics, but accepting
arbitrary executables, credentials in argv, or restoring over an active
database would create command-injection, disclosure, and rollback risks.

## Decision

Use prevalidated absolute ordinary paths to `pg_dump`, `pg_restore`, `createdb`,
`dropdb`, and `psql`; execute a closed argv without a shell; and reference
operator-managed libpq service names rather than credentials. Stream the custom
dump into an operator-keyed AES-256-GCM envelope with an authenticated bounded
header and exact plaintext size/SHA-256. Require the central
`operations.backup.create` or `operations.restore.execute` permission before
adapter invocation. Restore only into a newly created conservative database
name, validate the dump before creation, verify Alembic and ReconForge schema
presence afterward, and drop the new database on restore or verification
failure. Never overwrite or rename the source database automatically.

## Consequences

The application has an explicit authorized, encrypted, rollback-capable Team
PostgreSQL boundary. Native PostgreSQL 17 evidence covers an Alembic 0015 dump,
41-table restore, corrupt-dump failure, and removal of the partial target. The
live drill and adapter tests are complementary; cross-platform execution of the
adapter itself, libpq service-file custody, managed keys, HA/cutover, host loss,
cross-version restore, scheduling/retention, and RPO/RTO remain open. The
backup/restore matrix records these gaps and P1-PLAT-010 remains in progress.

## Reversibility

The adapter is optional and does not change database schemas. Encrypted
artifacts require this format reader and their operator key. An operator may
replace the adapter behind the application port only with equivalent
authorization, integrity, isolation, verification, and rollback evidence.
