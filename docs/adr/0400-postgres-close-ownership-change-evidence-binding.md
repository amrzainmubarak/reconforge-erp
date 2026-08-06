# ADR 0400: PostgreSQL close binds ownership-change evidence

- **Date:** 2026-08-06
- **Status:** Accepted

## Context

An ownership-change proposal persisted for a tenant must be attributable to
the exact consolidation close worksheet that consumed it. Tenant-wide lookup
does not prove the business period, reporting currency, or worksheet entity.

## Decision

Add migration `0071_pg_close_ownership_change_links` with forced RLS,
append-only triggers, run/artifact/entity uniqueness, and an immutable link
digest. Replay-verify the ownership-change artifact before linking it to a
prepared close run; bind period, currency, and subsidiary entity to the
worksheet; require an actor independent of the run preparer; and include
sorted result digests in the close bundle. Expose the operation only through
the PostgreSQL server API with strict IDs and `finance_core.manage`
authorization. Older bundles remain readable through the additive field.

## Boundary

This is evidence provenance for a non-posting proposal. It is not statutory
ownership-change accounting, goodwill approval, journal posting, ERP/bank
write-back, HA/DR, or production assurance.

## Reversibility

The migration downgrade refuses non-empty links before dropping the trigger,
function, index, and table.
