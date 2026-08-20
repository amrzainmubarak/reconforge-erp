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

Evidence includes a dedicated live CI runtime contract. The focused suite passed
4/4 static/contract tests locally and the live test passed under the
`reconforge_app_non_superuser` role in GitHub Actions run `30755552134` on
PostgreSQL 16 Alpine. It proves idempotent replay, tenant isolation, overlap
refusal, and immutable update refusal for synthetic data. It does not prove
restore, HA, RPO/RTO, SLO, or deployment readiness.
