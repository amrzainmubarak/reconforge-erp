# Accounts Payable Three-Way-Match Foundation

Migration 15 adds a bounded local Accounts Payable workflow for supplier master data,
purchase orders, posted goods receipts, supplier invoices, and deterministic three-way
matching. It is a finance-controls foundation, not a complete AP subledger.

## Supported lifecycle

```text
Supplier Active
    -> Purchase Order Draft -> Submitted -> Approved
    -> Posted Goods Receipt
    -> Supplier Invoice Draft -> Submitted
    -> Three-way Match Passed -> Approved
```

An invoice with a variance enters `Exception` and creates an open exception-queue
record. Re-running the match updates the deterministic match record and resolves the
prior AP exception when the inputs now pass. Purchase-order and invoice lifecycle
transitions use optimistic `row_version` checks. A known authenticated user cannot
approve their own purchase order or invoice; the compatibility `local-cli` actor is
reserved for explicitly local service operation.

## Financial representation

- Monetary fields are non-negative integer minor units, such as cents or piasters.
- Quantities are finite, positive `Decimal` values persisted as canonical text.
- Supplier, purchase-order, invoice, receipt, match, audit, and outbox identifiers are
  deterministic for the relevant business key.
- Invoice totals must equal the sum of line totals plus invoice-level tax.
- Receipts cannot exceed the ordered quantity for a purchase-order line.
- Supplier, purchase-order, invoice, and receipt currencies must be explicit; this
  slice requires the supplier currency and document currency to agree.

The current slice does not calculate exchange rates, statutory tax or withholding,
landed cost, accruals, or posting currency conversions.

## Match explanations

`run_three_way_match` compares each invoice line to its linked purchase-order line and
posted receipts. The result records quantity, unit-price, and line-total variances.
Stable reason codes include:

- `AP-3WM-MISSING-PO`
- `AP-3WM-UNKNOWN-LINE:<line-id>`
- `AP-3WM-QUANTITY:<line-id>`
- `AP-3WM-PRICE:<line-id>`

The associated `exceptions_queue` row retains the source match, workspace, control
code, risk rating, and workflow status. The local API exposes the match result through
`POST /api/v1/payables/invoices/{invoice_id}/match`.

## Idempotency and evidence

Purchase-order, goods-receipt, and supplier-invoice creation accept an optional
idempotency key scoped to the workspace and operation. Business writes, audit events,
and transactional-outbox events are committed together. Backup/restore includes all
AP tables and is covered by a round-trip test.

## Explicit non-goals

This release does not implement:

- AP accounting entries, invoice accruals, period posting, or statutory financial statements;
- payment proposals, payment batches, bank execution, or settlement reconciliation;
- credit/debit notes, prepayments, withholding, tax engines, or exchange-rate revaluation;
- vendor remittance, procurement approvals beyond the local PO lifecycle, or ERP writeback;
- PostgreSQL persistence, distributed workers, Redis coordination, or hosted tenant isolation.

Those capabilities require separate bounded contexts, versioned migrations, accounting
invariants, security/SoD tests, and source-system integration contracts.
