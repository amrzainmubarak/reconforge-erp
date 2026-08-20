# ADR 0479: PostgreSQL manufacturing cost-control parity

- **Date**: 2026-08-09
- **Status**: Accepted locally; hosted promotion remains pending

## Context

ADR 0478 intentionally delivered only local SQLite persistence for the
deterministic manufacturing cost-control report. The local API returned a
deliberate unsupported response in the PostgreSQL server profile, leaving the
module behind the retail and professional evidence boundaries.

## Decision

Add Alembic revision `0083_pg_manufacturing` and a tenant/workspace-scoped
PostgreSQL repository. The schema uses JSONB report/status projections,
forced row-level security, a tenant/workspace policy, exact digest constraints,
idempotent decision-digest replay protected by a transaction advisory lock, and
append-only update/delete triggers. Add request-scoped server API execution
through the existing PostgreSQL identity factory and `PostgresTenantBoundary`.
The route remains non-posting and network dispatch remains disabled.

## Evidence

Static schema/migration/API contracts pass. A disposable PostgreSQL 16 Docker
runtime with a non-superuser application role passes the manufacturing
repository test for migration SQL, RLS tenant isolation, idempotent replay,
read/list replay verification, and immutable update refusal. The container is
removed after the test. Hosted CI execution and independent failure domains
remain unverified.

## Boundary and rollback

This closes PostgreSQL server-profile evidence persistence only. It does not
claim live ERP/MRP interoperability, statutory or standard-cost valuation,
inventory/WIP/GL posting, write-back, HA/DR, production capacity, or hosted
release readiness. Downgrade refuses to discard non-empty evidence; remove the
route/helper/repository, Alembic revision, tests, and manifest entries only
after an operator-approved empty-data rollback.
