# ADR 0416: Bind intercompany evidence API policy to the full hierarchy

- **Status:** Accepted
- **Date:** 2026-08-07
- **Scope:** PostgreSQL intercompany elimination evidence API

## Context

Intercompany elimination artifacts are persisted under tenant/workspace RLS,
and the route already resolves an authenticated execution scope. Its central
ABAC calls, however, supplied only tenant/workspace and did not carry the
optional organization/legal-entity attribution used by the transaction.

## Decision

Pass organization and legal-entity scope to both the authenticated prepare and
read policy checks before the PostgreSQL adapter is called. Keep the existing
workspace payload equality check, replay verification, and non-posting boundary
unchanged.

## Evidence boundary

The focused route contract records both policy calls with exact tenant,
workspace, organization, and legal-entity values. This is one evidence route
family only; statutory posting, external provider/write-back, distributed
IAM, HA/DR, and production readiness remain unverified.

## Rollback

Remove the two hierarchy arguments, focused assertions, ADR, manifest entry, and
execution records. No schema or data rollback is required.
