# ADR 0019: First PostgreSQL Domain Boundary for Master Data

- Status: Accepted as a bounded server slice
- Date: 2026-07-23
- Decision owners: ReconForge maintainers

## Context

The PostgreSQL/RLS foundation and Alembic migration path existed, but no
domain repository consumed them. Calling that foundation hosted persistence
would overstate the implementation. Master data is a low-volume reference
bounded context with clear tenant and organization relationships, making it a
suitable first server-side slice.

## Decision

Add Alembic revision `0002_postgres_master_data` and
`PostgresMasterDataRepository`. The repository persists tenant-scoped
currencies, organizations, legal entities, and branches using parameterized
psycopg-compatible SQL. PostgreSQL enforces composite tenant-aware foreign
keys, uniqueness, checks, and forced row-level security. Repository methods
have deterministic ordering and never commit; callers must establish a
transaction-local tenant context through `PostgresTenantBoundary`.

The existing SQLite `MasterDataService` remains the default local
implementation. In the explicit authenticated PostgreSQL server profile,
summary, snapshot, currency, organization, legal-entity, branch, and
fiscal-period API operations route to this repository with no local fallback.
The fiscal-period schema is installed by Alembic revision
`0005_postgres_fiscal_periods`; its lifecycle is metadata-only and does not
lock source-ERP postings. The server route binds the verified principal to
mutation audit/outbox evidence in the caller-owned transaction.

## Consequences

- The server migration chain now contains one real domain context rather than
  only infrastructure tables.
- The authenticated server API has a usable tenant-scoped master-data slice
  for currencies, organizations, legal entities, branches, and fiscal periods;
  server operations fail closed instead of reading tenant-local SQLite.
- A tenant cannot reference another tenant's organization, currency, or legal
  entity through the composite foreign keys, even if application filtering is
  bypassed.
- The server profile is still incomplete: reconciliation, remaining finance,
  workflow, evidence, API sessions, workers, cache, object storage, and
  exports have not been migrated to PostgreSQL.
- Future changes must use expand-and-contract migrations and preserve the
  caller-owned transaction contract.

## Rejected alternatives

- Reusing the SQLite service through a PostgreSQL-looking adapter: this would
  hide the absence of real PostgreSQL persistence and weaken the boundary.
- Adding unscoped tables and relying only on repository `WHERE` clauses: this
  would not provide database-enforced tenant isolation.
- Migrating every domain in one change: the resulting migration and rollback
  surface would be too large to validate safely in one iteration.
