# Integration and retention administration runbook

This runbook covers migration `0052_security_governance` in the explicit
PostgreSQL server profile.

## Preconditions

- PostgreSQL is at Alembic head `0052_security_governance` or later.
- The caller is a human with `security.policy.manage` and current required
  step-up/MFA assurance.
- `X-ReconForge-Tenant` and an operator-owned cursor-signing key are configured.
- Back up and verify recovery before changing retention policy. Confirm legal,
  contractual, and records-management requirements with accountable humans.

## Integration operations

List active integrations with `GET /api/v1/admin/security/integrations`; use
`include_inactive=true` for disabled or expired entries. The governed kinds are
`federation_link`, `scim_credential`, `service_account`, and
`notification_route`. The list is a projection of their native runtime tables.

To disable, submit the current `state_digest` and one of
`administrative_cleanup`, `policy_change`, `security_response`, or
`user_request` to:

`POST /api/v1/admin/security/integrations/{kind}/{integration_id}/disable`

A digest conflict means the state changed: reread and review; do not blindly
retry. A successful transition immediately disables the native resource.
Service-account disable also revokes every active credential. SCIM credential
and federation-link disable use their native revocation/disable evidence.

## Retention operations

- `GET|POST /api/v1/admin/security/retention-policies`
- `PATCH /api/v1/admin/security/retention-policies/{policy_id}`
- `POST /api/v1/admin/security/retention-policies/{policy_id}/evidence/{evidence_id}`

Policy names are immutable lowercase identifiers. Duration is 1–36,500 days.
Updates require the current positive lifecycle version. Retire a policy with
`active=false`; policies and assignment records are not deleted.

Applying a policy computes `assigned_at + duration_days` and retains the later
of that value and the evidence's current floor. The evidence version increments
only when the floor extends. Replaying the same evidence/policy/policy-version
assignment is idempotent. A different policy version still requires the current
evidence retention version.

## Security and disclosure

Responses never include bearer tokens, credential hashes, external-subject
hashes, notification destinations, secret references, raw actor identifiers,
or evidence source references. Each transition appends a bounded domain-audit
event in the same transaction. Tenant RLS is forced for policy and assignment
tables, and native resources retain their existing RLS policies.

## Incident verification

After an emergency disable:

1. Reread with `include_inactive=true` and retain the returned audit event ID.
2. Verify the affected runtime path rejects authentication/login/delivery.
3. Review native lifecycle events and the domain audit chain through separately
   authorized audit tooling.
4. Rotate or replace external/provider credentials through their owning system;
   this API deliberately has no generic enable or secret-write operation.

## Recovery and claim boundary

Empty `0052 -> 0051 -> 0052` recovery is supported. A downgrade that would
discard policy, assignment, or advanced retention-version evidence refuses.
Retention here governs database metadata only; independently verify object-store
lock, backup/replica/export propagation, deletion workflows, and legal holds.
This runbook is not legal advice, compliance certification, provider
interoperability evidence, HA/DR proof, or Enterprise-readiness approval.
