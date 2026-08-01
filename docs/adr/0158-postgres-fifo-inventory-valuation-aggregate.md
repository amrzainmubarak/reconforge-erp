# ADR 0158: PostgreSQL FIFO inventory valuation aggregate

- **Status**: Accepted
- **Date**: 2026-07-28

## Context

Inventory valuation has eleven backend-neutral use cases but PostgreSQL had no
storage for policies, exact costs, immutable valuation lines, FIFO layers, or
layer consumptions. Inventory Core alone cannot prove cost ownership or create
balanced Finance drafts.

## Decision

Migration 0025 adds six tenant-keyed, forced-RLS tables. Currency values use
integer minor units and quantities use scaled integers with explicit precision.
Only FIFO is accepted because it is the only method implemented and tested by
the current contract. Database triggers protect Draft-only details, final
headers, balanced approval metadata, monotonic layers, and immutable
consumptions. The eleven-operation adapter follows as the next part of E-153.

## Consequences

- PostgreSQL can persist the same aggregate without binary floating point.
- Approval must reference a Posted movement and a balanced Draft or Validated
  Finance entry in the same tenant and currency.
- AVCO and Standard Cost remain unimplemented and unclaimed.
- Storage presence alone does not establish valuation parity.

## Rollback

Downgrade deletes the six valuation tables child-first and then removes their
trigger functions. Existing Inventory Core and Finance Core records remain.
