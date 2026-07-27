# Accounts Receivable and Credit-Control Foundation

Migration 20 adds a bounded local Accounts Receivable workflow for customer
master data, exact minor-unit sales invoices, approval-time credit controls,
posted receipts with allocations, credit exposure, and deterministic aging.
It is a finance-controls foundation, not a complete AR subledger.

## Supported lifecycle

```text
Customer Active
    -> Invoice Draft -> Submitted -> Approved
    -> PartiallyPaid -> Paid
```

An invoice cannot be approved when the customer is inactive, on credit hold, or
the invoice would exceed the configured credit limit unless the approver has the
`receivables.credit_override` permission and supplies a reason. A known
authenticated user cannot approve an invoice they created. Invoice and receipt
mutations use optimistic row versions where a second allocation is added.

## Financial representation

- Monetary values are non-negative integer minor units; no binary floating-point
  amount is accepted by the service.
- Quantities are finite, positive Decimal values stored as canonical text.
- Invoice line totals are checked against quantity multiplied by unit price using
  explicit half-up rounding. Invoice tax must equal the sum of line tax values.
- Customer, invoice, receipt, and allocation identifiers are deterministic for
  their workspace-scoped business keys.
- Customer and document currencies are explicit and must agree.

## Receipts, allocations, and aging

A posted receipt may be partially allocated, leaving an explicit unallocated
balance. Allocations must remain within the receipt amount, match the customer
and currency, and not exceed invoice outstanding value. Repeated allocation to
the same receipt/invoice pair accumulates the existing allocation rather than
creating duplicate rows. Invoice statuses advance to `PartiallyPaid` or `Paid`
deterministically.

`GET /api/v1/receivables/aging?as_of_date=YYYY-MM-DD` returns open invoices,
days overdue, `Current`, `1-30`, `31-60`, `61-90`, and `90+` bucket totals, plus
the total outstanding value. `credit-exposure` reports limit, exposure,
available credit, hold, and customer status.

## API and CLI

The authenticated API is under `/api/v1/receivables`:

- `POST/GET /customers`
- `POST/GET /invoices`
- `POST /invoices/{id}/submit`
- `POST /invoices/{id}/approve`
- `POST /receipts`
- `POST /receipts/{id}/allocate`
- `GET /credit-exposure/{customer_code}`
- `GET /aging`

The local CLI is under `reconforge receivables` and includes customer upsert,
invoice creation/submission/approval, receipt posting, customer listing,
receipt allocation, customer listing, invoice listing, credit exposure, and aging commands. Invoice and allocation
line files are strict JSON inputs; malformed or missing values fail with a
non-zero exit code.

Customer, invoice, receipt, and allocation business writes append audit and
transactional-outbox evidence before commit. Migration and backup/restore tests
cover all AR tables.

## Explicit non-goals

This release does not implement:

- statutory GL posting, revenue recognition, tax calculation, tax reporting, or
  multi-currency exchange-rate conversion;
- credit notes, refunds, dunning, collections work queues, promises to pay, or
  dispute management;
- sales orders, shipment/inventory integration, payment-gateway settlement, or
  source-ERP writeback;
- PostgreSQL AR persistence, hosted tenant shared-schema deployment, or
  distributed AR workers.

Those capabilities require separate migrations, posting and period invariants,
tax controls, integration contracts, and independent security/SoD coverage.
