# ADR 0317: Live authenticated consolidation-close API gate

- Status: accepted
- Date: 2026-08-04

## Decision

Extend the existing live PostgreSQL server-identity fixture with the
consolidation-close schema and least-privilege grants, then exercise
`GET /api/v1/consolidation-close/periods` through the real authenticated
FastAPI server path. The authorized workspace must return the PostgreSQL
source marker, while an equivalent sibling-workspace request must fail before
repository exposure.

## Rationale

The consolidation-close API was already hierarchy-bound and covered by local
mocked scope contracts, but it lacked a live authenticated route assertion.
The same fixture now proves middleware identity, request execution scope,
PostgreSQL RLS, and the route adapter together without inventing a separate
runtime harness or mutating production data.

## Boundary

The test uses synthetic data on one PostgreSQL 16 node and an empty close
period set. It proves route isolation and backend selection, not statutory
consolidation, posted close production behavior, independent HA/DR, live
ERP/bank integration, write-back, or production readiness.

## Rollback

Remove the fixture schema/grants/assertions and this ADR. No application
migration or persisted production data is changed.
