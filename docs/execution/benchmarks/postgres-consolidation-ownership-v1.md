# PostgreSQL consolidation ownership contract v1

Date: 2026-08-02 (Africa/Cairo)

Alembic revision `0054_pg_consol_ownership` adds a tenant-scoped
`reconforge.consolidation_ownership_interests` table. It stores exact
`NUMERIC` percentages, effective dates, approval lineage, source digest, and
workspace/group scope. Forced RLS uses transaction-local `app.tenant_id`, and
immutable triggers reject direct update/delete operations.

`PostgresConsolidationOwnershipRepository` reuses the typed ownership domain,
sets tenant scope inside each transaction, locks the subsidiary interval query,
rejects overlapping revisions, resolves one active interest per subsidiary,
and emits an audit event on creation. Alembic downgrade drops the table and
guard function.

Evidence currently covers static schema/migration/adapter contracts only:
4/4 focused tests and 6/6 inventory tests pass. No live PostgreSQL DSN was used
for this slice, so this report is not runtime parity, RLS isolation, restore,
rollback, SLO, or deployment evidence.
