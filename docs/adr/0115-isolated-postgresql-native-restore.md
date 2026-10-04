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
adapter invocation.

Restore only into a new conservative database name. Because `CREATE DATABASE`
cannot run in a transaction, the maintenance principal creates that target via
a closed `psql` command with `ALLOW_CONNECTIONS false`. A second, atomic
maintenance-database transaction enables connections and revokes `CONNECT`
from `PUBLIC`; the creating maintenance principal is the target owner and
keeps its implicit connection privilege. This removes the default-PUBLIC
connection interval before `pg_restore` can recreate routines. The adapter
then restores with `--no-owner --no-privileges`, revokes `PUBLIC EXECUTE` from
every restored user-schema `SECURITY DEFINER` function or procedure, and only
then verifies the target profile. On restore, hardening, or verification
failure it drops that exact target. Never overwrite or rename the source
database automatically.

The maintenance/restore principal is a protected migration principal, never a
runtime API or worker role. Runtime roles must not own the restore target,
hold a direct database-level `CONNECT` grant, be superusers, or be granted
membership that gives them those privileges. The restore output is an isolated
verification target, not a promoted production database; any later runtime
access requires a separate, reviewed provisioning action after verification.

## Consequences

The application has an explicit authorized, encrypted, rollback-capable Team
PostgreSQL boundary. Native PostgreSQL 17 evidence covers an Alembic 0015 dump,
41-table restore, corrupt-dump failure, and removal of the partial target. The
adapter contract additionally proves non-connectable target creation, atomic
removal of `PUBLIC CONNECT` before restore, post-restore security-definer ACL
hardening, and exact-target rollback on each failure path. The live drill and
adapter tests are complementary; cross-platform execution of the adapter
itself, libpq service-file custody, maintenance-role custody, managed keys,
HA/cutover, host loss, cross-version restore, scheduling/retention, and
RPO/RTO remain open. The backup/restore matrix records these gaps and
P1-PLAT-010 remains in progress.

## Reversibility

The adapter is optional and does not change database schemas. Encrypted
artifacts require this format reader and their operator key. An operator may
replace the adapter behind the application port only with equivalent
authorization, integrity, isolation, verification, and rollback evidence.
