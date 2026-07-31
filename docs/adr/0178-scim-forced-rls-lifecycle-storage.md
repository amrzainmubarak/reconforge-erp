# ADR 0178: SCIM lifecycle uses forced-RLS storage and atomic identity effects

- Status: accepted
- Date: 2026-07-28
- Task: P3-ENT-002 / E-173

## Context

SCIM provisioning changes identity state and can immediately affect access.
Persisting only a SCIM shadow record would leave existing sessions usable after
deprovisioning, while writing external groups into RBAC tables would let an
upstream system grant financial authority.

## Decision

Migration 0035 creates tenant-keyed, forced-RLS User, Group, membership, and
sanitized lifecycle-event tables. Every resource is additionally scoped by a
bounded provisioning domain. External resource identities are serialized with
a transaction advisory lock so concurrent delivery has one business effect.
Identical replay retains the stable server ID and version.

A provisioned User receives a local identity row with a random, discarded
password verifier and no role assignment. SCIM never receives or stores a raw
local password. Deactivation changes both records and revokes every existing
session in the same caller-owned transaction. Group membership may reference
only active SCIM Users in the same tenant and provisioning domain and never
writes to RBAC role or permission tables.

## Consequences

- Tenant RLS and domain foreign keys prevent cross-domain group membership.
- Deprovisioning fails closed for current sessions without deleting evidence.
- Username uniqueness remains tenant-wide, matching the service-provider
  uniqueness requirement; conflicting upstream identities are rejected.
- HTTP credentials, PATCH/filter/discovery behavior, conditional ETags, and
  hosted-provider interoperability remain separate slices.

## Rollback

Downgrade drops events, memberships, groups, then SCIM User links. Identity
rows created by provisioning are deliberately retained so rollback cannot
silently erase identities or audit-relevant session history. Operators must
review retained disabled identities before any later deletion.
