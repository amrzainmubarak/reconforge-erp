# ADR 0195: PostgreSQL is the authoritative server identity lifecycle

Status: Accepted  
Date: 2026-07-29

## Context

The PostgreSQL server profile authenticated users and sessions from PostgreSQL, but the historical `/api/v1/users` routes still mutated a tenant SQLite database. That created two identity control planes: a caller could authenticate against PostgreSQL while an apparently successful administration action changed only SQLite. Session rows also lacked optimistic versions and attributable revocation reasons.

## Decision

- Add a backend-neutral identity-administration Application port and a tenant-bound PostgreSQL adapter.
- Expose server-only, cursor-paginated user and session metadata at `/api/v1/admin/identity/*`.
- Require `users.manage`, a human principal, and the centrally configured current step-up/MFA method for every route.
- Make user enable/disable and session revocation optimistic through positive lifecycle versions.
- Disabling a user revokes every unrevoked session in the same transaction. The status effect, session effects, and bounded domain-audit event commit or roll back together.
- Refuse self-disable and refuse disabling the last active identity carrying `users.manage`.
- Store closed revocation reason codes and attributable actor identifiers. Public responses expose only presence flags for client IP and user agent and never expose email, password material, bearer tokens, token hashes, raw IP addresses, or raw user-agent values.
- In the server profile, fail the historical `/api/v1/users` SQLite routes with `local_identity_surface_disabled`. Community/local mode retains those routes unchanged.
- Keep role and policy lifecycle out of this slice. The historical `/api/v1/roles` surface remains a documented server-profile gap until E-192 replaces or disables it.

## Consequences

- Migration 0050 adds lifecycle metadata, closed consistency constraints, and bounded pagination indexes.
- SCIM deactivation/reactivation participates in the same identity lifecycle constraints and records `scim_deactivation` session revocation.
- Downgrade is permitted only when no governed lifecycle evidence would be lost; otherwise it fails before schema mutation.
- The current audit event is written to the existing domain audit chain. Consolidating all administration event stores and building the accessible administration UI remain separate work.

## Rollback

Remove the four server routes and their authorization inventory entries, restore the previous PostgreSQL/SCIM writes, and downgrade 0050 only after exporting or explicitly discarding governed lifecycle evidence. Community SQLite data and routes require no migration.
