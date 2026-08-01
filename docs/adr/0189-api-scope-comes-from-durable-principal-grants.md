# ADR 0189: API execution scope comes from durable principal grants

Status: Accepted  
Date: 2026-07-29

## Context

PostgreSQL RLS can enforce workspace and entity isolation only when the request
transaction receives an authentic scope. A client header is a selector, not an
authorization source. Treating a workspace or entity header as authority would
let a tenant member select a sibling hierarchy. Leaving headers optional would
preserve an accidental tenant-wide path across financial and Evidence APIs.

## Decision

- Store active and revoked user/service-account grants in the forced-RLS,
  append-only `principal_scope_grants` ledger.
- Validate grant targets against the current tenant's authoritative workspace,
  organization, or legal-entity table.
- Load an immutable active-grant snapshot during bearer authentication and bind
  it to `ServerPrincipal`; client input cannot enlarge that snapshot.
- Require `X-ReconForge-Workspace` for PostgreSQL business operations. Optional
  organization and legal-entity selectors must also exist in the snapshot, and
  a legal entity requires an organization.
- Reject missing, malformed, and unauthorized scope before opening the business
  database transaction. Pass only the authorized selection to
  `PostgresTenantBoundary` for transaction-local RLS settings.
- Keep identity and grant administration explicitly tenant-global.
- Manage grants through human-only, step-up protected `roles.manage` endpoints.
  Revocation records actor and reason and never deletes history.

## Compatibility

Community/SQLite behavior is unchanged. PostgreSQL business clients must select
an authorized workspace after migration 0046. Existing principals receive an
empty snapshot until grants are assigned, so access fails closed. `/auth/me`
exposes only the caller's active authorized IDs for client selection.

## Evidence required

- Fresh migration plus direct and long rollback/re-upgrade paths.
- Non-superuser grant, snapshot, revocation, invalid-target, and tenant-RLS tests.
- HTTP grant lifecycle under privileged human authorization.
- Missing and sibling scope rejection before a database connection opens.
- Boundary tests proving the hierarchy reaches every PostgreSQL business transaction.

## Consequences

This closes header spoofing and accidental tenant-wide business access in the
current server surfaces. It does not prove external IdP group-to-scope mapping,
production assignment, independent penetration testing, or Enterprise readiness.
