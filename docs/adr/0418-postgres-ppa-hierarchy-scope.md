# ADR 0418: Add hierarchy scope to PostgreSQL PPA evidence

- **Status:** Accepted
- **Date:** 2026-08-07
- **Scope:** Consolidation purchase-price-allocation evidence

## Context

PPA evidence was immutable and tenant-RLS protected, but its persistence table
did not retain the organization/legal-entity hierarchy already present in the
authenticated request. Central ABAC could therefore be more specific than the
stored artifact boundary.

## Decision

Migration `0076_pg_consolidation_ppa_scope` adds nullable organization and
legal-entity attribution with defaults from transaction-local scope, foreign
keys, a hierarchy-aware result-digest uniqueness constraint, index, and forced
RLS predicates. The repository accepts optional scope, includes it in scoped
artifact identity, filters legacy rows explicitly, and preserves the old
tenant-only digest identity when no hierarchy is supplied. The server adapter
passes the optional request headers into both transaction GUCs and repository.

## Compatibility and rollback

Legacy rows remain readable only through an unscoped compatibility request;
scoped requests cannot see NULL-attributed legacy rows. Downgrade restores the
tenant-only uniqueness/policy and drops only the additive columns after the
standard migration safety checks. No payload or posting behavior changes.

## Evidence boundary

Static migration, repository, API compatibility, replay, and package contracts
are local evidence. A live PostgreSQL non-privileged hierarchy/isolation run is
still required before promoting this slice beyond bounded evidence.
