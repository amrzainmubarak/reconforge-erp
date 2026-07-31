# ADR 0194: Security Center is count-only and human-governed

## Status

Accepted on 2026-07-29.

## Context

Enterprise identity, session, federation, SCIM, service-account, emergency,
scope, evidence-retention, notification, and audit state already exists across
separate forced-RLS tables. An administration screen that reads those tables
directly or returns subject rows would create broad identity disclosure and a
second authorization implementation. A green posture label would also imply
security assurance that this repository has not earned.

## Decision

- Add a backend-neutral `SecurityCenterApplicationService` over a count-only
  repository protocol. The PostgreSQL adapter issues one static parameterized
  projection inside the request tenant transaction.
- Expose `GET /api/v1/admin/security/overview` only in the PostgreSQL server
  profile. It requires the dedicated `security.center.read` permission, a human
  principal, and the configured recent privileged assurance method.
- Return only closed aggregate sections for identity, sessions, integrations,
  policy, retention, and audit. Do not return usernames, emails, IPs, user
  agents, credential/token hashes, external subjects, destinations, secret
  references, financial rows, free-form audit text, or cluster-global audit
  sequence values. Even a tenant-filtered maximum of a global sequence is an
  avoidable cross-tenant activity side channel.
- Bind the snapshot to the tenant through a one-way scope digest and to one UTC
  whole-second `as_of` value. Canonical JSON produces a deterministic snapshot
  digest. Count inconsistencies fail closed.
- Label the result `operational_snapshot_not_security_assurance`. Audit-chain
  state is explicitly `not_evaluated_use_audit_verify_endpoint`; the overview
  never translates absence of count-based findings into compliance or a secure
  verdict.
- Migration 0049 adds a named database constraint that prevents direct service-
  account assignment of `security.center.read`. The central policy engine and
  service-account Application validation independently enforce the same rule.

## Consequences

- Administrators get one bounded status surface without acquiring raw subject
  or secret inventory through it.
- Aggregate counts can still reveal organization size and security-control
  adoption; the permission and MFA boundary therefore remains mandatory.
- This slice does not provide identity mutation, policy editing, session
  revocation, integration configuration, retention mutation, audit browsing,
  an administration UI, accessibility evidence, hosted interoperability, or
  independent assurance. P3-ENT-006 remains in progress.

## Rollback

Downgrading 0049 restores the prior service-account permission ceiling. No data
table is added or removed. Existing code must stop exposing the route before
downgrade so a future direct grant cannot bypass the database-level human-only
constraint.
