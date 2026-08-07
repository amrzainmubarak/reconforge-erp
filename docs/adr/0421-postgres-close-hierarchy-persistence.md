# ADR 0421: Persist hierarchy scope for PostgreSQL consolidation-close records

- **Date**: 2026-08-07
- **Status**: Accepted

## Context

The close and certification repositories now carry the authenticated
tenant/workspace/organization/legal-entity scope, but the PostgreSQL close
tables did not persist organization or legal-entity attribution.  Tenant-only
RLS therefore could not provide a database-level boundary for close evidence.

## Decision

Add migration `0078_pg_close_scope` and the reusable
`POSTGRES_CONSOLIDATION_CLOSE_SCOPE_SCHEMA_SQL` helper.  The migration adds
nullable transaction-defaulted organization and legal-entity columns to all
eleven close tables, tenant-safe foreign keys, hierarchy indexes, and forced
RLS predicates.  Close periods and runs also apply the existing workspace
scope.  Legacy rows remain readable only in unscoped compatibility mode.

Replace tenant-only uniqueness with `UNIQUE NULLS NOT DISTINCT` constraints
over the persisted hierarchy so legacy NULL scope retains its old identity
while scoped records cannot collide across organizations or legal entities.

## Rollback

Downgrade refuses to discard any non-NULL hierarchy attribution, removes the
new policy/foreign-key/index/constraint state, drops the additive columns, and
restores the original tenant-only policies and uniqueness constraints.  This
is a reversible schema change, not a claim of live PostgreSQL verification.

## Boundaries

Focused contracts, static migration checks, package membership, Ruff, Mypy,
and local regression are required evidence.  A live PostgreSQL hierarchy
isolation run, statutory consolidation posting, provider write-back, HA/DR,
and production release approval remain separate gates.
