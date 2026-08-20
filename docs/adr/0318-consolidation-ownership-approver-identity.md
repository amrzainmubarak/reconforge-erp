# ADR 0318: Verify consolidation ownership approver identity at save time

- Status: accepted
- Date: 2026-08-04

## Decision

The consolidation ownership save path must resolve `approved_by` to a real,
enabled identity in the same backend and require that identity to hold
`finance_core.manage` or `finance_core.validate`. The approver must be
different from the authenticated preparer. SQLite resolves the identity from
the local user repository; PostgreSQL resolves it through the tenant-scoped
identity repository while the ownership transaction is still under the
authenticated tenant/workspace boundary.

Unknown, disabled, or self-referential approvers fail with a structured
`consolidation_ownership_approver_invalid` error. A known user without a
governed finance permission fails with
`consolidation_ownership_approver_unauthorized`. The route does not treat a
client-supplied string as evidence of review, and it does not claim a separate
approver session, MFA ceremony, or statutory consolidation approval.

## Rationale

The previous API contract preserved an independent-looking `approved_by`
field but did not verify that the referenced reviewer existed or was allowed
to review finance ownership. Enforcing the check inside the save operation
closes that maker-checker identity gap without duplicating persistence logic or
weakening local-first SQLite compatibility.

## Evidence and boundary

The local API contract rejects an unknown approver; the live PostgreSQL
server-identity fixture creates and uses a reviewer identity, grants the
required ownership permissions, and still proves sibling-workspace refusal.
The evidence is synthetic, single-node PostgreSQL and one API process. It does
not prove an independent browser/session approval, universal enterprise IAM,
statutory consolidation, live ERP/bank providers, write-back, HA/DR, or
production readiness.

## Rollback

Remove the identity lookup helpers, route checks, tests, documentation, and
manifest entry. Existing ownership rows and migrations require no rollback.
