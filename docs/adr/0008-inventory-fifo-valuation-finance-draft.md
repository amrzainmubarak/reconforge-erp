# ADR 0008: FIFO valuation prepares a separate Finance Core Draft

- Status: Accepted
- Date: 2026-07-22

## Context

Migrations 9 and 10 established exact local inventory movements, derived on-hand, governed counts, and reorder advice without monetary costing. The next safe slice needs reproducible cost-layer evidence and balanced accounting preparation while preserving the established boundaries: source exports remain evidence, local Posted movements are not ERP postings, and Finance Core validation is a separate review decision.

Silently inferring receipt costs, consuming layers out of order, mutating approved evidence, or validating an accounting entry during inventory approval would make the control trail difficult to explain and would collapse separation-of-duties boundaries.

## Decision

1. Add migration 11 with entity-scoped FIFO policies, valuation documents, inbound cost evidence, valuation lines, cost layers, and immutable layer consumptions.
2. Implement `InventoryValuationService` over an `InventoryValuationRepository` protocol, with SQLite as the current repository.
3. Accept exact per-line total cost only for inbound Receipt and positive Adjustment lines. Never infer it from quantity, an export, or a supplier document.
4. Value Delivery and negative Adjustment lines by consuming the oldest eligible Approved layer for the same entity, item, UOM, and lot/serial.
5. Enforce chronological approval and reject backdated valuation after a later Approved document.
6. Keep Transfers outside valuation because this slice does not model an entity ownership change.
7. Store quantity and money as scaled integers; reject binary floats and atomically fail partial allocations that cannot produce a meaningful minor-unit value.
8. On valuation approval, atomically write immutable valuation evidence, update layer balances, and create one balanced Generated Finance Core entry with status `Draft`.
9. Never validate the Finance Core entry automatically. Reject policies that would require unmapped mandatory dimensions.
10. Block voiding an Approved valuation's source movement. Correction is supplied later by the explicit exact-mirror design in [ADR 0009](0009-exact-fifo-valuation-reversal.md).
11. Expose separate manage/approve permissions, known-user creator/approver separation, audit events, strict API/CLI/contracts, schema-aware backup/restore, public local export, and a synthetic read-only Studio projection.

## Consequences

- FIFO quantities and values are reproducible from immutable origin and consumption evidence.
- Inventory approval and Finance Core validation remain distinct review boundaries.
- Exact minor-unit storage avoids binary floating-point drift; a rare unrepresentable partial allocation fails visibly.
- Existing stock-to-GL export reconciliation and canonical files remain unchanged.
- Required-dimension inference, AVCO, landed cost, manufacturing costing, partial or chained reversal, foreign currency, and source-ERP writeback require later designs. Migration 12 implements the bounded exact whole-valuation reversal described by ADR 0009.
- SQLite is the verified adapter; cross-database behavior remains unclaimed.
