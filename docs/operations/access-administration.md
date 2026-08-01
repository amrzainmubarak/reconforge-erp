# Access administration runbook

This runbook covers the bounded PostgreSQL server-profile role and access-policy
lifecycle introduced by migration `0051_access_policy_lifecycle`.

## Preconditions

- The database is at Alembic head `0051_access_policy_lifecycle` or later.
- The caller is a human with `roles.manage` and current required step-up/MFA.
- `X-ReconForge-Tenant` is present and the API has an operator-owned cursor key.
- At least two independent active administrators are recommended before removing
  authority. The database transaction still prevents loss of the final manager.

## Surfaces

- `GET /api/v1/admin/access/permissions`
- `GET|POST /api/v1/admin/access/roles`
- `PATCH /api/v1/admin/access/roles/{role_id}`
- `PUT /api/v1/admin/access/roles/{role_id}/permissions`
- `PUT /api/v1/admin/access/users/{user_id}/roles`

Permission and role sets are exact replacements, not incremental guesses. Read
the current lifecycle version, submit the intended complete set, and handle a
version conflict by rereading and reviewing the new state. Unknown permissions
are rejected because permission registration is not an HTTP capability.

## Security behavior

- Role policy or user-role changes revoke every still-active session affected by
  the change. Users must authenticate again.
- Role retirement revokes assignments and sessions. Reactivation does not restore
  old assignments.
- The last effective active `roles.manage` authority cannot be removed.
- Responses contain names, descriptions, counts, lifecycle state, and digests;
  they never contain passwords, tokens, hashes, email addresses, IP addresses,
  or user-agent values.
- Every transition appends a bounded domain-audit event in the same transaction.

## Recovery

An empty/unchanged `0051 -> 0050 -> 0051` rehearsal is supported. Downgrade after
governed lifecycle activity exits with
`refusing to discard governed access-policy lifecycle evidence` and leaves the
head and rows unchanged. Never bypass the guard. Restore a verified backup or
use a reviewed forward migration.

## Claim boundary

This proves a tenant-scoped, optimistic, audited RBAC lifecycle on the tested
PostgreSQL profile. It does not prove HA, production key custody, external IAM
interoperability, full ABAC, policy certification, or Enterprise readiness.
