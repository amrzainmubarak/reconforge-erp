# ADR 0180: Service accounts are role-free machine principals

Date: 2026-07-29

Status: Accepted

## Context

Long-lived user passwords, copied browser sessions, and role assignment are unsafe foundations for unattended jobs. A machine identity needs bounded credentials, direct least-privilege grants, explicit ownership, deterministic revocation, and evidence that cannot be rewritten. It must not silently inherit human approval, identity-administration, or emergency-access authority.

## Decision

- Service accounts are separate tenant-scoped records and are never represented by an `identity_user`, password, user session, or role membership.
- Each account receives 1-32 explicit permissions already present in the tenant permission registry. Human-only identity, policy, service-account administration, and emergency permissions are denied in both Python and PostgreSQL constraints.
- Credentials are opaque, returned once, stored only as SHA-256 digests, expire in 5 minutes to 90 days subject to a stricter per-account ceiling, and support atomic successor rotation and revocation.
- Disabling an account increments its optimistic version and revokes every active credential in the same transaction. Permission replacement is also version guarded; existing credentials immediately observe the new permission snapshot.
- PostgreSQL triggers enforce immutable account/credential identity, monotonic account versions, permission ceilings, account-scoped rotation, TTL, and append-only lifecycle events. All four tables use forced RLS.
- Operator CLI commands create, issue, rotate, revoke, and disable. The DSN should come from `RECONFORGE_POSTGRES_DSN`; raw tokens are printed only by issue/rotate.

## Consequences

This slice establishes the service-account lifecycle but does not yet authorize service credentials on HTTP routes. Privileged human sessions, step-up authentication, break-glass access, review workflow, and API machine-principal composition remain mandatory parts of P3-ENT-003.

## Rollback

Disable all service accounts, revoke credentials, preserve an approved export of append-only lifecycle metadata if required, then downgrade migration 0037 to 0036. The rollback removes only the new service-account aggregate and leaves user, federation, and SCIM identity state intact.
