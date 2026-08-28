# ADR 0578: Current PostgreSQL identity governance runtime evidence

## Status

Accepted — 2026-08-23

## Context

Enterprise governance requires runtime proof that identity lifecycle, scope
authority, and privileged step-up controls fail closed under a non-privileged
PostgreSQL application role. Static policy tests are insufficient for RLS,
session invalidation, and append-only assurance.

## Decision

Run the current identity-administration, scope-authority, privileged-session,
policy-scope, and policy-analysis runtime suites against the disposable
PostgreSQL service. Count the result as bounded evidence only with the declared
application role and both tenant and append-only checks passing.

## Limits

This is synthetic single-host PostgreSQL evidence. It does not prove an
external IdP, SSO/SAML/OIDC interoperability, universal MFA coverage,
production PAM, distributed session revocation, or independent IAM assurance.
