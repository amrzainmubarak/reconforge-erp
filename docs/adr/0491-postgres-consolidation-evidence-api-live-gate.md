# ADR 0491: Live PostgreSQL gate for consolidation evidence APIs

- **Date:** 2026-08-10
- **Status:** Accepted

## Decision

Promote the existing server-profile API routes for acquisition deferred-tax
and consolidation impairment evidence to a current bounded PostgreSQL runtime
gate. The gate uses a clean PostgreSQL 16 Alpine database, a non-superuser
and non-`BYPASSRLS` application role, authenticated bearer sessions, strict
request reconstruction, maker-checker actor separation, forced tenant RLS,
idempotent POST replay, replay-verified GET responses, and sibling-tenant
denial. The stored artifacts remain explicitly `posted: false`.

The live fixture installs the direct schema contracts, including the existing
hierarchy-attribution schema for nullable organization/legal-entity columns.
It does not claim that the Alembic upgrade path was exercised by this gate.

## Rationale

The routes and repositories already had local contracts and migration-backed
adapters, but the API boundary had not been exercised over a clean authenticated
PostgreSQL server profile. A narrow HTTP gate closes that evidence gap without
adding a SQLite fallback, a posting path, a live provider, or a valuation/tax
policy opinion.

## Boundaries

- Evidence is synthetic and single-node.
- The artifact is tenant-scoped in this API gate; no workspace isolation claim
  is added when the request omits hierarchy headers.
- No statutory tax accounting, impairment methodology, journal posting,
  write-back, live bank/ERP provider, restore drill, HA/DR, RPO/RTO, or hosted
  CI claim is made.
- Alembic migration execution remains a separate compatibility concern.

## Verification

`tests/test_api_consolidation_tax_impairment_live.py` passes the deferred-tax
and impairment POST/GET/replay/idempotency/sibling-tenant assertions on the
clean runtime. The ownership-change live fixture also passes after explicitly
installing its privileged-session and emergency-access dependencies.

## Rollback

Remove the new live test and evidence promotion, or revert this additive ADR
and documentation. No application data is modified by the fixture after its
cleanup transaction.
