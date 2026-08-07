# ADR 0415: Bind evidence policy checks to the full execution hierarchy

- **Status:** Accepted
- **Date:** 2026-08-07
- **Scope:** PostgreSQL evidence registry API

## Context

Evidence routes already restored organization and legal-entity scope into the
PostgreSQL transaction boundary, but the central ABAC checks still evaluated
only tenant and workspace. A request could therefore pass the policy boundary
without proving the same hierarchy used by row-level security.

## Decision

Pass optional organization and legal-entity identifiers from the authenticated
execution scope to every server evidence read, manage, and verify policy check.
This covers list, coverage, record, drill-down, registration, linking,
requirements, and checksum verification. The existing sensitive drill-down
permission and local SQLite behavior remain unchanged.

## Evidence boundary

The focused API contract records the exact four-part hierarchy for all seven
policy calls while the fake repository remains tenant-bound. This is one route
family only; complete API/job/export/UI adoption, federation, distributed
invalidation, live providers, HA/DR, and production IAM remain unverified.

## Rollback

Remove the hierarchy arguments, focused assertions, ADR, manifest entry, and
execution records. No schema or data rollback is required.
