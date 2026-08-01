# Administration security overview

## Boundary

`GET /api/v1/admin/security/overview` is a read-only PostgreSQL server-profile
surface. It is unavailable in Community/SQLite mode. It reports aggregate
operational observations, not a compliance result, penetration test, risk
acceptance, or security certification.

The caller must be a human user with `security.center.read` and recent step-up.
If WebAuthn is configured, user-verified WebAuthn is required. Service accounts
cannot receive or exercise the permission. Responses use `Cache-Control:
no-store` through the global API security-header boundary.

## Returned information

The v1 schema returns counts for users/roles, sessions/MFA, configured or linked
integration state, scope and emergency policy state, evidence retention and
verification, and audit volume. It also returns deterministic attention codes.
It never returns subject rows, credential material, destinations, source
financial data, free-form audit content, or cluster-global audit sequence
values.

`chain_verification` is deliberately not evaluated in this aggregate query.
Call `GET /api/v1/admin/audit/verify` with its separate human `audit.verify`
permission and current privileged assurance for the authoritative source-chain
check. Do not display the overview posture as a green security verdict.

## Operational checks

1. Verify the database is at migration 0049 or later.
2. Create `security.center.read` in the tenant permission registry and grant it
   only to a reviewed human role.
3. Verify step-up/MFA before granting access.
4. Compare `snapshot_digest` only when `as_of`, runtime configuration, and
   tenant scope are the same.
5. Investigate every returned attention code through the narrower authorized
   lifecycle surface; never infer a subject identity from counts.

No mutation or bulk action is implemented in this slice. User/role lifecycle,
session termination, integration and retention administration, accessible UI,
and exit-audit consolidation remain P3-ENT-006 work.
