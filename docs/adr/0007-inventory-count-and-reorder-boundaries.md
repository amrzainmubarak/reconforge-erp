# ADR 0007: Separate governed inventory counts from reorder advice

- Status: Accepted
- Date: 2026-07-22

## Context

Migration 9 established exact local inventory movements and derived on-hand. Physical counts require immutable expected snapshots, controlled result entry, independent approval, and safe variance handling. Reorder rules require current balance reads and exact thresholds, but they do not require or authorize procurement execution.

Combining both concerns inside the already large inventory-core service would weaken domain boundaries. Automatically posting count variances or creating purchase orders would also expand authorization and financial risk beyond this slice.

## Decision

1. Add migration 10 with separate count-session, count-line, and reorder-rule tables.
2. Implement `InventoryPlanningService` over an `InventoryPlanningRepository` protocol, with SQLite as the current repository.
3. Snapshot non-zero Posted location balances when a Draft count starts; make expected fields immutable.
4. Require completed exact counts, reasoned submission, and independent known-user approval.
5. Refuse approval when the Posted location balance changed after the snapshot.
6. Generate a linked Draft Adjustment movement only for non-zero approved variance. Never post it automatically.
7. Derive reorder signals deterministically from active rules and current Posted local on-hand. Never create RFQs or purchase orders.
8. Expose strict local API/CLI/contracts, audit events, backup/restore, sanitized export, and synthetic read-only Studio records.

## Consequences

- Count evidence and approvals have a clear lifecycle and database-enforced immutability.
- Quantity corrections retain a second review/posting boundary in Inventory Core.
- Reorder advice remains useful without pretending Purchasing exists.
- Storage-specific SQL is isolated for later repository contract testing.
- Counts currently exclude zero-balance items and reject concurrent Posted balance changes; blind counts and count freezes need a later design.
- Inventory valuation and finance-core integration remain explicitly unimplemented.
