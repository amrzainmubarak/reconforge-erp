# ADR 0182: Privileged actions require session-bound reauthentication

Date: 2026-07-29

Status: Accepted

## Context

Possession of an eight-hour human session is insufficient assurance for
identity administration, policy-affecting finance operations, close control,
inventory posting, or credit-control override. ReconForge does not yet have a
verified MFA provider, so it must neither label password reauthentication as
MFA nor leave privileged server actions protected only by the original login.

## Decision

- The PostgreSQL server profile requires recent step-up for the closed
  `PRIVILEGED_STEP_UP_PERMISSIONS` registry. Community/SQLite behavior remains
  compatible because it has no server-session assurance boundary.
- `POST /api/v1/auth/step-up` re-verifies the current local human password,
  against the same user and bearer session, using the existing lockout-aware
  password verifier. Service accounts fail before password processing.
- A successful assertion is append-only, forced-RLS, bound to tenant, user and
  session, capped at ten minutes by the application and fifteen minutes by the
  database, and never outlives the parent session.
- Middleware snapshots active assurance from PostgreSQL on every request.
  Revoked or expired sessions cannot reuse an assertion. Policy still requires
  the underlying role permission; step-up never grants authority.
- API denials use `step_up_required` so a client can request reauthentication
  without disclosing permissions the user does not already possess.

## Consequences

Privileged PostgreSQL actions now require both existing RBAC authority and
recent session-bound password reauthentication. This is stronger than relying
on the original session but is not MFA, phishing-resistant authentication, or
emergency access. Federated and SCIM-provisioned users without a usable local
password cannot step up through this adapter; an approved external MFA/ACR
adapter remains future work.

P3-ENT-003 remains open for separately governed emergency-access request,
approval, expiry and post-use review.

## Rollback

Revoke active human sessions, downgrade migration 0038 to 0037, and remove the
step-up requirement from the server policy composition. This deletes only the
new assertion records and route behavior; roles, users, sessions, service
accounts, federation and SCIM state remain unchanged.
