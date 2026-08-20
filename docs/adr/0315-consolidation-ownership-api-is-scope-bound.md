# ADR 0315: Scope-bound consolidation ownership API

- Status: accepted
- Date: 2026-08-04

## Decision

Expose the existing immutable, effective-dated consolidation ownership master
through two additive `/api/v1/consolidation-ownership` operations: an
authenticated `POST /interests` mutation and an authenticated `GET /effective`
resolution. Mutations use strict exact-decimal text, bind `prepared_by` to the
authenticated principal, and retain the declared independent approver. Local
mode uses the existing SQLite repository; server mode uses the PostgreSQL
repository inside the authenticated tenant/workspace/organization/entity RLS
boundary. The server query cannot select a sibling workspace, and the route
family is included in the startup authorization inventory.

## Rationale

The ownership master already had deterministic domain validation and SQLite /
PostgreSQL persistence, but consumers had no API contract. Adding the API at
the application boundary makes effective-date resolution usable without
duplicating calculation or bypassing the existing immutable repositories.

## Security and financial boundary

The route rejects binary floating-point JSON for percentages, unknown mutation
fields, invalid date/version/digest input, and workspace mismatches. PostgreSQL
RLS remains the database control and the route verifies the authenticated
hierarchy before repository access. The API accepts the declared approver
identifier; it does not yet prove that the approver has independently
authenticated in the same request. This slice is not statutory consolidation,
full maker-checker identity proof, live ERP/bank integration, write-back,
HA/DR, or production-readiness evidence.

## Compatibility and rollback

The change is additive: existing SQLite repositories, CLI contracts, schemas,
and PostgreSQL migrations are unchanged. Rollback removes the route/server
adapter, authorization inventory entry, tests, manifest entry, and this ADR;
persisted ownership rows remain intact.
