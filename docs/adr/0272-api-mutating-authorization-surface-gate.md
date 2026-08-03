# ADR 0272 — Fail-closed mutating API authorization surface

- **Status:** Accepted
- **Date:** 2026-08-03
- **Scope:** FastAPI route authorization inventory

## Decision

At application construction, validate the closed route inventory as a
mutation-policy surface. `POST`, `PUT`, `PATCH`, and `DELETE` operations must
either carry an explicit `all`/`any` permission contract, use the governed
`dynamic` policy boundary, or belong to the separately classified SCIM
protocol. Public and identity-only mutations are limited to explicit
authentication/WebAuthn/step-up handshake allowlists.

An unlisted public or identity mutation, a permissionless protected mutation,
or an unknown authorization mode raises before the app is returned. The
existing route inventory digest remains unchanged; this is a runtime fail-closed
validation layer over that inventory.

## Rationale

Route dependency presence alone can regress when a new mutation is added with
the wrong dependency or allowlist entry. A construction-time gate turns that
drift into a deterministic failure and makes route/action coverage reviewable
without pretending that federation, emergency-access policy administration,
field masking, or every UI/job/export surface are complete.

## Limits

This slice covers API route/action classification only. It does not implement
OIDC/SAML/SCIM provisioning, distributed policy-cache invalidation, complete
ABAC administration, or cross-surface (jobs/exports/UI) coverage.

