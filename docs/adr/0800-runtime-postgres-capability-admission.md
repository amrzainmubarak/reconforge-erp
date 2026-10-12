# ADR 0800: Reject PostgreSQL runtime capabilities that bypass row isolation

Date: 2026-10-03

Status: Accepted

## Context

The existing per-lease guard rejects privileged role flags, ownership and
server-file access. Those checks still admitted ordinary roles with TRUNCATE,
schema/database CREATE or callable SECURITY DEFINER grants. A disposable live
database reproduced tenant A truncating tenant B's row and a definer function
returning both tenants' count despite a tenant A transaction-local scope.
The destructive probe rolled back and verified both original rows remained.

## Decision

Extend the same catalog query to reject effective TRUNCATE, TRIGGER or REFERENCES
on non-system tables; CREATE on the current database or non-system schemas; and
EXECUTE on non-system SECURITY DEFINER functions or procedures. Evaluate each
SET/ADMIN-reachable identity, including inherited and PUBLIC grants. Do not
reject a role merely because it has a membership with no effective INHERIT,
SET or ADMIN route to the capability. Recheck every pooled lease and discard a
rejected physical connection, without automatically editing deployment grants.

Installed trigger/event-trigger routines remain trusted database schema code.
They cannot be called directly as ordinary functions. Existing inventory
integrity triggers continue to run; runtime CREATE/TRIGGER privileges that
could install new triggers are denied. This is a conservative runtime profile,
not semantic analysis of routine bodies or a sandbox against trusted DBA changes.
The separate administration factory remains available for migrations and restore.

## Compatibility and verification

There is no data migration. Previously accepted, overprivileged deployments must
correct their runtime grants before API/worker checkout succeeds. Preserve
explicit DML grants needed by each adapter. The regression suite exercises
direct, inherited, SET-then-inherited and ADMIN-then-inherited grants; PUBLIC
defaults; inaccessible memberships; procedure/trigger distinctions; pool drift,
revocation and subsequent recovery. Retained before/after evidence is linked
from the execution log. The guard cannot stop an administrator changing grants
after checkout or an application using the shared role to select a different
tenant scope; application authorization and database administration stay trusted.

Rollback reverts the admission query without changing stored data, but restores
the demonstrated privilege gap. Correcting deployment grants is the preferred
recovery. See [operator contract](../security/postgres-runtime-grants.md).

## References

- [PostgreSQL 16 row-security rules](https://www.postgresql.org/docs/16/ddl-rowsecurity.html)
- [PostgreSQL 16 privileges](https://www.postgresql.org/docs/16/ddl-priv.html)
- [PostgreSQL 16 SECURITY DEFINER behavior](https://www.postgresql.org/docs/16/sql-createfunction.html)

Official documentation checked 2026-10-03; the implementation targets the
repository's PostgreSQL 16+ membership semantics.
