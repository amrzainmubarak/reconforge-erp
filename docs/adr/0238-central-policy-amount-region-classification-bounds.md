# ADR 0238: Central policy enforces amount, region, and data-class bounds

- Status: accepted
- Date: 2026-08-02

## Decision

Extend `central-policy-v1` with exact finite `Decimal` amount floors/ceilings,
region scope, and data-classification scope. Missing authorization for a
supplied region or classification denies access. Amount bounds are inclusive;
non-finite amounts and inverted bounds are rejected before evaluation.

## Boundary

This is a policy-engine contract slice. It does not claim that every API, job,
export, or UI route has been migrated to supply these attributes, and it does
not close OIDC/SAML/SCIM, policy administration, cache invalidation, or
PostgreSQL RLS for the full enterprise IAM workstream.

## Rollback

Remove the additive context fields, checks, tests, ADR, and execution entries.
Existing callers that omit the new optional attributes retain compatibility.
