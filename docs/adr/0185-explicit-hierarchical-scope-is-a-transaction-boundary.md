# ADR 0185: Explicit hierarchical scope is a transaction boundary

Status: Accepted

## Context

Tenant RLS prevented cross-tenant access, but PostgreSQL transactions carried no uniform workspace or legal-entity context. Per-query filters cannot prove the same isolation for every repository, worker, export, storage operation, and failure path.

## Decision

Server operations use an immutable tenant, workspace, organization, and legal entity execution scope. The four values are validated and installed with transaction-local PostgreSQL settings. Empty child values mean an explicitly tenant-wide administrative operation; supplied values add fail-closed RLS constraints. A legal entity cannot be supplied without its organization.

Migration 0041 applies the first hierarchical policies to the authoritative workspace and master-data hierarchy. Further slices must bind jobs, exports, object storage, and domain tables before P3-ENT-004 can close.

## Consequences

- Commit and rollback clear scope automatically; pooled connections cannot retain a prior request's hierarchy.
- Existing tenant-wide callers remain compatible.
- This slice proves the hierarchy foundation only, not complete multi-entity isolation or Enterprise readiness.
