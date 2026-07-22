# ADR 0006: Inventory Uses A Separate Exact-Quantity Control Ledger

- Status: Accepted
- Date: 2026-07-22

## Context

ReconForge already reads `stock_moves.csv` and related ERP exports for deterministic stock-to-GL and work-order reconciliation. Those rows are source evidence with established field meanings and report behavior. Turning them into mutable warehouse transactions would break compatibility and blur the boundary between imported evidence and locally governed state.

The platform also needs credible inventory primitives before costing, purchasing, manufacturing, or warehouse UI workflows can be built: item/UOM identity, warehouse/location scope, exact quantities, lot/serial traceability, controlled posting, immutability, on-hand derivation, and explainable exceptions.

## Decision

1. Add migration 9 without changing canonical export schemas or existing reconciliation behavior.
2. Store local inventory masters and movements in separate tables.
3. Store quantities as scaled integers using an immutable per-item UOM precision snapshot; reject binary floating-point input.
4. Use explicit Receipt, Delivery, Transfer, and Adjustment direction rules.
5. Permit only `Draft -> Posted -> Voided`; `Posted` means the local inventory ledger only.
6. Recheck references, period state, serial uniqueness, and projected stock inside an atomic SQLite write transaction.
7. Protect non-Draft headers and lines with service rules and SQLite triggers.
8. Default locations to negative-stock protection while permitting an explicit exception-oriented override.
9. Derive deterministic negative-stock, expired-stock, and missing-account exceptions.
10. Include inventory tables in schema-aware backup/restore and sanitized public export coverage.
11. Defer monetary valuation and GL integration to a separately tested contract rather than inferring cost from quantity.

## Consequences

- Existing export reconciliation remains backward compatible.
- Local on-hand quantities are reproducible from immutable Posted movements.
- This foundation supports future valuation, counts, reorder rules, purchasing, and manufacturing slices without claiming those workflows now.
- SQLite is the verified backend; cross-database behavior remains unclaimed until repository/transaction contract tests exist.
- Voiding affects local on-hand and is therefore blocked when it would violate protected-location or serial constraints.
