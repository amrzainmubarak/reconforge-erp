# ADR 0490: Expose a PostgreSQL ownership-change evidence API without posting

- **Date:** 2026-08-10
- **Status:** Accepted for the bounded server slice
- **Decision owners:** ReconForge maintainers

## Decision

Expose authenticated `POST /api/v1/consolidation-ownership-change` and
`GET /api/v1/consolidation-ownership-change/{artifact_id}` routes over the
existing PostgreSQL ownership-change evidence repository. The routes require
`finance_core.manage` for preparation and either `finance_core.read` or
`finance_core.manage` for replay. The authenticated principal is always the
prepared-by actor; the request cannot supply that identity.

The server helper executes through the existing tenant boundary and optional
organization/legal-entity scope. The repository remains forced-RLS,
append-only, idempotent, and replay-verifying. The domain result is explicitly
`posted: false`; this slice creates no journal, ledger, ERP, bank, or network
side effect.

## Rationale

The domain and PostgreSQL persistence slices already produced deterministic,
balanced ownership-change proposals, but server users could only attach an
already-created artifact to a close run. A permissioned create/read boundary
closes that operational gap while preserving maker-checker separation,
authenticated actor binding, and the non-posting claim.

## Rejected alternatives

- Accepting a client-supplied `prepared_by` would permit actor spoofing.
- Falling back to SQLite in server mode would weaken tenant/RLS guarantees.
- Posting directly from this route would conflate evidence preparation with a
  separate policy-approved ledger workflow and is outside the current slice.

## Verification and rollback

Focused local API, authorization-inventory, domain replay, and PostgreSQL
repository tests are required. The opt-in live server test must prove
non-superuser authentication, replay, sibling-workspace denial, and
non-posting output. Rollback is additive: disable the route/factory and revert
the code/documentation; no evidence rows are deleted or rewritten.

## Boundary

This ADR does not establish statutory accounting treatment, live provider
interoperability, journal posting, write-back, HA/DR, hosted CI success, or
production readiness.
