# ADR 0399: PostgreSQL ownership-change evidence remains non-posting

- **Date:** 2026-08-06
- **Status:** Accepted

## Context

`ownership-change-adjustment-v1` computes an exact three-line proposal for a
change in group ownership and NCI. The domain contract is policy-neutral and
must not silently become a statutory posting engine. It nevertheless needs a
tenant-isolated persistence boundary for replay and close lineage.

## Decision

Add migration `0070_pg_ownership_change` and
`PostgresConsolidationOwnershipChangeRepository`. Store canonical request and
result JSONB, recompute request/result digests on persistence and read,
require distinct identity actors through database foreign keys, make retries
idempotent by tenant/result digest, emit an audit creation event, and reject
posted/update/delete paths. Artifact IDs use the strict `ownchg-<sha256>`
contract.

## Boundary

This stores an approved source-bound proposal only. It does not determine
statutory ownership-change treatment, goodwill, tax, legal-book entries,
journal posting, ERP write-back, or production readiness.

## Reversibility

The downgrade refuses non-empty artifacts before dropping the trigger,
function, index, and table.
