# ADR 0419: Add hierarchy scope to impairment and deferred-tax evidence

- **Status:** Accepted
- **Date:** 2026-08-07
- **Scope:** Consolidation impairment and acquisition deferred-tax evidence

## Decision

Migration `0077_pg_imp_tax_scope` adds nullable
organization/legal-entity attribution, transaction-local defaults, parent
foreign keys, hierarchy-aware result uniqueness, indexes, and forced-RLS
predicates to both immutable evidence tables. Their repositories and server
adapters accept the optional hierarchy and use explicit NULL-aware scope
predicates so scoped requests cannot read unscoped legacy rows.

## Compatibility and rollback

Requests without hierarchy retain the existing tenant-only artifact identity and
can replay legacy rows. Scoped requests are isolated from NULL-attributed rows.
The downgrade restores tenant-only uniqueness and policies before dropping only
the additive columns; no payload or posting behavior changes.

## Evidence boundary

Local migration, repository, API, replay, and package contracts are bounded
evidence. A live non-superuser PostgreSQL hierarchy/isolation run remains
required; statutory tax/impairment judgments, posting, providers, HA/DR, and
production readiness are not claimed.
