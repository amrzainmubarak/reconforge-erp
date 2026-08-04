# ADR 0319: Expose a scoped consolidation-close period write boundary

- Status: accepted
- Date: 2026-08-04

## Decision

Add `POST /api/v1/consolidation-close/periods` as the first authenticated
write surface for the existing governed close lifecycle. The request uses a
strict schema for group, period, currency, and ISO date values. Local mode
uses the existing SQLite application/repository boundary; server mode uses the
request-scoped PostgreSQL repository under the authenticated tenant,
organization, legal-entity, and workspace boundary. Repeating the same
period identity replays the persisted period; a different workspace is
rejected before repository access.

The route requires `finance_core.manage`, binds the actor from the authenticated
principal, and does not create a run, post a journal, lock a period, or mutate
an external source system.

## Rationale

The close API previously exposed period/run evidence and certification but had
no authenticated route for entering a period. Adding only the period boundary
creates a useful vertical slice without inventing a second lifecycle or
weakening the backend-neutral application port.

## Evidence and boundary

Local tests prove strict unknown-field rejection and same-identity replay. The
live server-identity fixture proves PostgreSQL persistence, authenticated actor
binding, and sibling-workspace refusal. Evidence is synthetic, one API process,
and one PostgreSQL node. It does not prove statutory consolidation, full close
posting, external ERP/bank write-back, independent HA/DR, or production
readiness.

## Rollback

Remove the route, request model, tests, inventory update, docs, and manifest
entry. No database migration or persisted-period rollback is required.
