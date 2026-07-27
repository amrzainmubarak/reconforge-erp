# ADR-0013: Bounded Accounts Payable Three-Way Match

- Status: Accepted
- Date: 2026-07-23
- Scope: local SQLite finance-controls foundation

## Context

ReconForge needs a real ERP-adjacent Accounts Payable workflow while preserving its
honest local-first positioning. A complete AP module would also require accounting
posting, tax and withholding, payments, settlement, period controls, and source-system
integration. Implementing those concerns in one untested module would create a larger
financial correctness risk than it would remove.

## Decision

Implement migration 15 as a bounded AP slice containing:

- supplier master records;
- purchase orders and exact-quantity lines;
- posted goods receipts with over-receipt protection;
- supplier invoices linked to purchase-order lines;
- deterministic quantity/price/total three-way matching;
- exception-queue routing and resolution;
- optional idempotency keys and optimistic row versions;
- RBAC, known-user separation of duties, audit events, and transactional outbox events;
- versioned FastAPI routes and backup/restore support.

Money is stored as integer minor units and quantities as canonical decimal text. The
match result is authoritative only for the local control workflow; it does not create a
statutory journal entry or payment instruction.

## Consequences

The repository now contains a testable purchase-to-receipt-to-invoice control path with
stable evidence and clear exception reasons. It can be extended without pretending that
AP payment or accounting behavior exists. The trade-off is an intentionally incomplete
workflow: accounting, tax, payment, credit-note, and ERP-writeback features remain
separate roadmap work and must not be inferred from an `Approved` AP workflow status.

## Rejected alternatives

- A fake generic ERP abstraction without persistence or invariants was rejected.
- Floating-point monetary storage was rejected because it weakens exact variance checks.
- Automatic invoice approval without a passed match and SoD check was rejected.
- Treating the local control ledger as a statutory subledger was rejected; the existing
  Finance Core contract explicitly remains a local control ledger.
