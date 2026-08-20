# ADR 0492: Alembic-head gate for consolidation evidence APIs

- **Date:** 2026-08-10
- **Status:** Accepted

## Decision

Add a second, stronger runtime gate for the existing deferred-tax and
impairment evidence APIs. The fixture provisions a fresh PostgreSQL 16 Alpine
database, runs the repository's Alembic chain through `head` (`0085_pg_reversal_definer`),
grants only the required tables to a non-superuser/non-`BYPASSRLS` application
role, and then exercises the authenticated API contract.

The gate covers strict actor binding, maker-checker separation, forced tenant
RLS, idempotent POST replay, replay-verified GET responses, sibling-tenant
denial, and explicit `posted: false` output. It does not add posting or provider
behavior.

## Rationale

The prior E-653 gate used direct schema SQL to isolate the HTTP boundary. An
Alembic-head run is required to prove that the same boundary is reachable from
the supported migration path and that the current schema lineage is usable by
the non-privileged runtime.

## Boundaries

- Evidence is synthetic, tenant-scoped for requests without hierarchy headers,
  and single-node.
- This proves migration-head compatibility, not downgrade/rollback, restore,
  HA/DR, RPO/RTO, or hosted CI.
- No statutory tax accounting, impairment valuation methodology, journal
  posting, live bank/ERP provider, or write-back claim is made.

## Verification

The E-654 live test runs `alembic upgrade head` against the clean database and
passes both API routes. The ownership-change live test also passes after its
explicit schema dependencies are installed.

## Rollback

Remove the E-654 test and evidence promotion or revert this additive ADR and
documentation. The disposable database is removed after each run; no product
data is changed by the fixture.
