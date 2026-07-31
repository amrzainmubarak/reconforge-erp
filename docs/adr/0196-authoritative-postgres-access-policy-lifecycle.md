# ADR 0196: PostgreSQL is the authoritative server access-policy lifecycle

- Status: Accepted
- Date: 2026-07-29
- Scope: E-192 / P3-ENT-006 role, permission-policy, and user-role administration

## Context

The PostgreSQL server profile authenticated users from tenant-scoped RBAC tables,
but role and role-permission writes were bootstrap helpers without optimistic
versions, retirement evidence, session invalidation, or an administrative API.
The historical `/api/v1/roles` reads still opened the Community SQLite store in
server mode. That split could display a policy different from the one used for
authorization.

## Decision

1. PostgreSQL is the only role and access-policy authority in the server profile.
   The legacy SQLite role routes fail with `local_identity_surface_disabled`
   before a local database connection is opened; local mode remains compatible.
2. `AccessAdministrationApplicationService` owns backend-neutral validation.
   The PostgreSQL adapter performs each mutation, domain-audit append, affected
   user version increment, and active-session revocation in one caller-owned
   tenant-scoped transaction.
3. Role names are immutable. Roles are retired and may be reactivated; they are
   not deleted. Retirement revokes active assignments, and reactivation never
   resurrects them.
4. Role-permission and user-role changes replace an exact, sorted set under an
   expected lifecycle version. Assignment rows retain lifecycle and revocation
   metadata. Every affected active session is revoked with `access_change`.
5. The tenant permission registry is list-only on the administrative API.
   Permission creation remains an operator/bootstrap concern so an API caller
   cannot invent a policy string and turn it into authority.
6. A serialized transaction may not retire the last management role, remove
   `roles.manage` from its final effective role, or strip the last active human
   manager's effective authority.
7. All six `/api/v1/admin/access/*` operations require a human `roles.manage`
   principal and the central server step-up/MFA policy. Signed role cursors bind
   tenant, retirement filter, ordering, and tie-breaker.

## Consequences

- Authorization reads ignore retired roles and revoked role/permission
  assignments. Security-center counts reflect active effective RBAC state.
- Existing active rows migrate at lifecycle version 1. Downgrade is allowed only
  while no governed lifecycle evidence would be discarded; otherwise it fails.
- Bootstrap helpers no longer mutate descriptions on conflict and cannot attach
  new authority to a retired role.
- This is a bounded single-node PostgreSQL administration contract. It is not a
  complete ABAC language, policy approval workflow, production IAM assurance,
  accessible administration UI, or compliance certification.

## Rollback

On an unchanged migration, downgrade `0051` to `0050` and deploy the previous
code together. After any governed role, policy, or assignment lifecycle change,
the downgrade deliberately refuses evidence loss. Restore from a verified backup
or migrate the lifecycle evidence through an explicitly reviewed successor; do
not drop the columns or re-enable the SQLite shadow surface.
