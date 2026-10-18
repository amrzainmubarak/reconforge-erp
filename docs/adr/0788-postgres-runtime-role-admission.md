# ADR 0788: Validate PostgreSQL runtime privileges on every checkout

- Status: Accepted
- Date: 2026-10-03
- Owners: Security / PostgreSQL

## Context

Forced RLS cannot constrain a superuser or BYPASSRLS identity. The previous runtime
factory accepted those credentials, owners and roles able to acquire dangerous
privileges. A safe initial connection also did not prove a reused lease stayed safe.

## Decision

Separate migration factories from guarded API/worker factories. On every runtime
checkout inspect PostgreSQL 16+ catalogs before business transactions, then roll
back the probe. Reject superuser, BYPASSRLS, CREATEROLE, CREATEDB, replication,
server file/program capabilities, unsafe database/schema/relation/routine
ownership and identities reachable through SET or effective ADMIN membership.
Check inherited ownership using actual privilege semantics. Reject changed
session identity, disabled row security and persisted tenant/scope settings.
Discard the physical connection on rejection or an unverifiable catalog result.

Keep the administrative factory available for migrations and restore. API
readiness uses the guarded factory, and reconciliation/outbox/scheduler workers
wrap their supplied factory with the runtime guard.

## Verification and limitations

Live tests exercise dangerous credentials, membership chains (including inherited
ADMIN with SET disabled), actual self-grant capability, safe inherited-only
special flags, ownership, privilege drift, sticky scope, pool discard and scoped
reuse. Normal workers are exercised separately with a nonprivileged role.

This prevents deployment misconfiguration and detects drift at checkout. It does
not defeat a hostile database administrator, changes made during a lease, or
arbitrary SQL execution as a shared application role able to set tenant GUCs.
Hard end-to-end isolation additionally requires authorized scope propagation,
parameterized access, database policy coverage and protected credentials.
See [PostgreSQL row security](https://www.postgresql.org/docs/16/ddl-rowsecurity.html)
and [role grant semantics](https://www.postgresql.org/docs/16/sql-grant.html).

## Rollback

No schema change. Provision a conforming application role if admission rejects an
existing deployment; keep migration ownership on separate credentials. Reverting
the guard must not be described as successful tenant isolation.
