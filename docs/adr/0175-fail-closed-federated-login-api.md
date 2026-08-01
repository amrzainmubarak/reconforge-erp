# ADR 0175: Fail-closed federated login API composition

- Status: Accepted
- Date: 2026-07-28

## Context

The cryptographic OIDC/SAML adapters and durable PostgreSQL federation stores existed as separate boundaries. A public login route must compose them without automatic provisioning, externally supplied authorization, token-directed network access, tenant ambiguity, assertion disclosure, or unaudited denial.

## Decision

Add `POST /api/v1/auth/federated-login` as an explicitly public authentication operation whose strict request rejects unknown fields and unsafe provider identifiers. The route is unavailable unless PostgreSQL server identity plus operator-owned providers and verifiers are supplied to the application factory. It executes verification, atomic replay consumption, local identity binding, session issue, and a sanitized final outcome audit inside one tenant-scoped transaction. It returns one uniform 401 response for assertion or link denial and never returns provider claims. Air-gap policy is passed to the provider-neutral service. The session is the existing hash-only PostgreSQL session, so the existing authenticated logout route remains its revocation boundary.

## Consequences

- No federation configuration exists by default; local Community login is unchanged.
- External groups may only select locally allowlisted roles and can never provision or widen a local user.
- Public-route inventory gains one digest-addressed operation.
- Durable audit stores only provider ID, allowed/denied outcome, and a bounded reason code; raw assertions, subjects, issuers, groups, and tokens are excluded.
- Operator configuration loading and a real signed assertion through the HTTP surface remain required before closing P3-ENT-001.

## Rollback

Remove the route from the app factory and authorization inventory. Existing local and PostgreSQL password login/session/logout contracts remain compatible. Migration 0034 may be downgraded only after retaining required federation audit evidence and removing dependent links.
