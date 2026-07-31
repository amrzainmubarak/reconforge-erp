# Identity and session administration

This runbook covers the PostgreSQL server profile introduced by migration 0050. It is a bounded operational control, not proof of compliance, production readiness, or independent security assurance.

## Preconditions

- PostgreSQL schema is at `0050_identity_admin_lifecycle` or later.
- The API uses a non-superuser `NOBYPASSRLS` database role.
- An operator-owned cursor signing key is configured.
- A human administrator has `users.manage` and a current step-up. If WebAuthn is configured for privileged actions, the step-up must be user-verified WebAuthn.

## Safe workflow

1. List `/api/v1/admin/identity/users` and retain the target `id`, `lifecycle_version`, and `state_digest`.
2. Confirm the target and reason outside ReconForge according to the operator's change process.
3. Send the desired `disabled` state with the exact observed lifecycle version.
4. Treat `identity_lifecycle_version_conflict` as a required reread; never retry with a guessed version.
5. Verify the returned audit event ID and, for disable, `revoked_sessions`.
6. List the target sessions and verify they are revoked. A disabled identity must fail new and existing authentication.

Self-disable is refused. Disabling the last active `users.manage` identity is refused. Enabling an identity does not restore old sessions; the user must authenticate again.

## Session response

List sessions with optional `user_id` and signed cursor pagination. Responses reveal only whether IP and user-agent metadata were recorded. They never return bearer tokens, hashes, raw IPs, or raw user-agent strings.

Revoke a session with its current lifecycle version and one reason: `access_change`, `administrative_cleanup`, `security_response`, or `user_request`. Revoking the caller's current session succeeds and invalidates its next request.

## Failure and recovery

- A database or audit failure rolls back the complete mutation.
- A sibling-tenant user or session identifier behaves as not found beneath RLS.
- If migration downgrade reports that governed evidence would be lost, retain 0050. Export and review the lifecycle/audit evidence before any approved destructive cleanup.
- Use the separately authorized audit verification command/endpoint to verify the domain audit chain; the administration response does not claim chain verification.

## Known limits

Role/policy mutation, integration and retention administration, consolidated audit browsing, accessible administration UI, hosted identity-provider interoperability, HA/DR, and external assurance are not provided by this slice.
