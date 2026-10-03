# PostgreSQL application-role admission

API connections and governed workers check effective capabilities before each
application transaction begins. A rejected lease is discarded. The public API
reports a safe degraded/unavailable outcome; it does not expose DSNs or catalog
details. Administration for migrations and backups uses a separate factory.

The runtime login must have no elevated role flags, application-object ownership,
server-file/program capabilities, persistent tenant scope or active SET ROLE.
It must also lack these effective grants, including through PUBLIC, inheritance,
SET ROLE chains or ADMIN membership that can re-enable SET:

| Object | Rejected runtime privilege |
| --- | --- |
| Current database | CREATE |
| Non-system schema | CREATE |
| Non-system ordinary, partitioned or foreign table | TRUNCATE, TRIGGER, REFERENCES |
| Non-system SECURITY DEFINER function or procedure | EXECUTE |

Use explicit SELECT/INSERT/UPDATE/DELETE grants for the tables the application
needs, schema USAGE and the necessary sequence privileges. Avoid `GRANT ALL`.
Existing installed trigger routines continue to enforce integrity; trigger and
event-trigger functions are excluded from the direct-call check. Trusted
administrators remain responsible for reviewing installed triggers and policies.

When a deployment fails admission after an upgrade:

1. Use an administrative session to inspect the runtime role's effective object
   privileges, inherited memberships and SET/ADMIN routes. Include PUBLIC grants
   and default privileges that would affect newly created objects.
2. Remove the unnecessary capability at its actual grant source. Revoking a
   direct grant does not neutralize an inherited or PUBLIC grant. Review shared
   database impact before changing shared-role or PUBLIC privileges.
3. Recheck with runtime credentials and run health plus an authorized transaction.
   The next lease uses a new connection after an unsafe pooled connection was
   discarded; no restart-only cached safety flag is used.

The application never performs blanket grant revocations. Normal scoped DML,
approved schema-installed triggers and separate administration remain supported.
This admission policy detects deployment mistakes and changes between leases;
it does not make a shared database role independent of trusted application code
or prevent concurrent DBA changes after a lease is checked.

Reproduction and compatibility decisions: [ADR 0800](../adr/0800-runtime-postgres-capability-admission.md).
