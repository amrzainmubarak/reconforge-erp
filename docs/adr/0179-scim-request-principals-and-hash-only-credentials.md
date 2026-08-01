# ADR 0179: SCIM request principals use separate hash-only credentials

Date: 2026-07-28

Status: Accepted

## Context

SCIM provisioning clients are machine actors. Reusing browser sessions, accepting a tenant from an unauthenticated claim, or storing replayable bearer values would weaken tenant isolation and credential revocation. SCIM Group membership must also remain separate from ReconForge authorization.

## Decision

- SCIM 2.0 is exposed only under `/scim/v2` in the explicit PostgreSQL server profile.
- Every request supplies a tenant routing header and an opaque bearer credential. The header enters forced RLS; successful lookup of the credential hash inside that tenant is the authority for tenant, provisioning domain, client identity, expiry, and revocation state.
- Only SHA-256 token digests are stored. A raw token is returned exactly once by the operator CLI. Rotation creates the successor and revokes its predecessor in one tenant transaction.
- SCIM request principals are not users and do not receive RBAC roles. Provisioned Groups never map to ReconForge permissions.
- Mutations require weak ETags through `If-Match`; deletion deactivates Users and revokes their sessions instead of deleting identity evidence.
- The supported RFC 7643/7644 subset is advertised through authenticated discovery. Unsupported Bulk, sorting, arbitrary filters, attributes, PATCH paths, and schemas fail closed.

## Consequences

Operators must bootstrap and rotate credentials through `reconforge scim credential-*` using a non-superuser PostgreSQL application role. A compromised tenant routing header alone grants nothing, and a credential cannot cross tenants or provisioning domains. The current evidence does not establish hosted identity-provider interoperability, OAuth authorization-server behavior, MFA, production approval, or broad Enterprise readiness.

## Rollback

Disable the PostgreSQL SCIM route by omitting the server profile, revoke active credentials, and downgrade migration 0036 to 0035. Existing provisioned identities and lifecycle evidence remain available at 0035; the HTTP credential table is removed.
