# ADR 0244: Local delegation administration is immutable and tenant-scoped

- **Status:** Accepted
- **Date:** 2026-08-02

## Context

The central policy evaluator can already enforce an explicit expiry, but an
enterprise policy surface also needs a durable local record for who granted,
approved, and revoked temporary authority. A mutable or cross-tenant record
would make replay and audit claims unsafe.

## Decision

Add a versioned SQLite `policy_delegations` table and typed repository. Grant
identity, scopes, permissions, time window, and approval identity are
immutable. The only allowed mutation is an active-to-revoked transition by an
independent actor. Effective reads require tenant, workspace, and an explicit
timezone-aware evaluation instant; expired or revoked grants return no result.

## Consequences and limits

This is a local Community-mode administration slice with migration and
repository contract tests. It does not claim OIDC/SAML/SCIM federation,
PostgreSQL RLS parity, emergency access, policy cache invalidation, or API/UI
coverage. Those remain open work items.
