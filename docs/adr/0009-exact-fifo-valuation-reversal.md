# ADR 0009: FIFO corrections use an exact compensating movement

- Status: Accepted
- Date: 2026-07-22

## Context

Migration 11 made Approved FIFO valuation evidence immutable and protected its source movement and generated Finance Core Draft. A correction mechanism must preserve that evidence, reverse stock and cost effects reproducibly, and retain the separate Finance Core validation decision. Editing layers, deleting consumptions, or creating an approximate journal would break the audit trail and could make quantity and money diverge.

## Decision

1. Add migration 12 with valuation-reversal headers and immutable per-layer `Restore` or `Remove` effects.
2. Require a separately created and Posted compensating inventory movement before a reversal Draft can be created.
3. Require the compensating movement to match workspace, organization, legal entity, line order, item, UOM, lot/serial, quantity, and precision, while swapping locations exactly. Map `Receipt -> Delivery`, `Delivery -> Receipt`, and `Adjustment -> Adjustment`.
4. Never edit or cancel the original Approved valuation. Permit only one active reversal for an original valuation and one active use of a compensating movement.
5. Restore the exact immutable consumptions of an outbound valuation. Remove an inbound layer only while its entire original quantity and value remain untouched; otherwise require dependent outbound valuations to be reversed first.
6. Apply layer effects and approve the reversal in one transaction with compare-and-swap balance checks and database trigger verification.
7. Create a separate Generated Finance Core `Draft` by copying the original accounts and dimensions and swapping every debit and credit. Never validate it automatically.
8. Protect an Approved reversal's mirror movement, Finance Core entry, finance lines, finance dimensions, header, and layer effects from silent mutation or voiding.
9. Use distinct reversal manage/approve permissions, known-user creator/approver separation, sanitized audit events, strict API/CLI/JSON contracts, schema-aware backup/restore/export, and a synthetic read-only Studio projection.

## Consequences

- The original stock, valuation, consumption, and accounting-control evidence remains inspectable.
- Quantity and minor-unit value corrections are reproducible from explicit immutable effects.
- Inbound corrections must follow dependency order; this slice intentionally does not infer a reversal chain.
- Finance Core validation remains an independent review action after inventory reversal approval.
- Partial reversal, reversal-of-reversal, AVCO, landed cost, manufacturing costing, foreign-currency conversion, statutory posting, and source-ERP writeback remain outside this decision.
- SQLite is the verified adapter; cross-database behavior remains unclaimed.
