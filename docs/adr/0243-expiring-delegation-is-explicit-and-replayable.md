# ADR 0243: Expiring Delegation Is Explicit and Replayable

- Status: accepted
- Date: 2026-08-02
- Scope: central policy engine

## Decision

Delegated authority carries a stable delegation identifier, a timezone-aware
expiry instant, and an explicit evaluation instant. The policy engine denies
missing evaluation time and denies at or after expiry. It never reads the wall
clock implicitly, so the same policy input and evaluation instant produce the
same decision.

## Boundary

This slice governs policy evaluation only. It does not create a delegation
administration store, OIDC/SAML/SCIM provider, or emergency-access workflow;
those remain separate capabilities with their own evidence gates.

## Rollback

The new context fields are optional and preserve existing callers. Removing the
fields and tests is a source-compatible rollback; no database migration is
required.
