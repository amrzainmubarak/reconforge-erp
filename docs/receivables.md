# Accounts Receivable and Credit-Control Foundation

SQLite migration 20 adds a bounded Accounts Receivable workflow for customer
master data, exact minor-unit sales invoices, approval-time credit controls,
posted receipts with allocations, credit exposure, and deterministic aging.
PostgreSQL persistence is provided by migration `0022_postgres_receivables` and
the scoped server adapter. It is a finance-controls foundation, not a complete
AR subledger.

## Supported lifecycle

```text
Customer Active
    -> Invoice Draft -> Submitted -> Approved
    -> PartiallyPaid -> Paid
```

Invoice approval requires an Active customer and the same currency as the
customer's financial history. These conditions cannot be bypassed with a credit
override. A credit hold or credit-limit breach can be overridden by an authorized
approver with `receivables.credit_override` and a recorded reason. The invoice
creator cannot approve the same invoice, including trusted local calls and
actor labels differing only by case or outer whitespace. Invoice and receipt
mutations retain optimistic row versions where a second allocation is added.

Customer currency can change only before the first invoice or receipt exists.
Any financial history freezes it, including Draft or Cancelled invoices, paid
invoices and unallocated receipts. Same-currency profile, status, hold and credit
limit updates remain available. Lowering a credit limit does not undo existing
approvals; it applies to subsequent approval decisions. Legacy currency
mismatches cause invoice/receipt creation, allocation, approval and credit-exposure
reads to fail closed and require an explicit data reconciliation; this change does not
silently convert or repair old records.

SQLite acquires its writer lock before reading the mutable customer profile and
credit exposure. PostgreSQL serializes profile updates, invoice creation,
receipt posting/allocation, approval and exposure reads through the customer
row with `FOR NO KEY UPDATE`. This includes concurrent first customer upserts.
Two approvals for one customer cannot both consume the same available credit.
Audit or outbox failure rolls back the corresponding business effect.

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
the total outstanding value and its `currency_code`. Its existing amounts and
item fields are preserved for a single currency. An empty report has
`currency_code: null` and zero totals. This endpoint rejects mixed-currency open
items with HTTP 400 instead of adding incompatible minor units.

`GET /api/v1/receivables/aging-by-currency?as_of_date=YYYY-MM-DD` returns a
separate versioned contract for mixed-currency workspaces:

```json
{
  "schema_version": 1,
  "as_of_date": "2026-08-01",
  "currency_groups": [
    {
      "currency_code": "JPY",
      "items": [{
        "invoice_id": "ARINV-SYNTHETIC-JPY",
        "invoice_number": "INV-JPY",
        "customer_code": "CUS-JPY",
        "customer_name": "Synthetic Customer",
        "currency_code": "JPY",
        "invoice_date": "2026-07-01",
        "due_date": "2026-07-31",
        "total_minor": 700,
        "outstanding_minor": 700,
        "days_overdue": 1,
        "bucket": "1-30"
      }],
      "bucket_totals_minor": {"Current": 0, "1-30": 700, "31-60": 0, "61-90": 0, "90+": 0},
      "total_outstanding_minor": 700
    }
  ]
}
```

Each group contains its contributing items, totals only that currency's integer minor
units, and appears in currency-code order. There is no report-wide monetary
total and no implicit currency conversion. Paid invoices and zero outstanding
balances do not create groups. An empty report has `currency_groups: []`.
The Python application/facade exposes the same contract through
`aging_report_by_currency`. No database migration is required.

Both endpoints age **currently open balances** against due dates using
`as_of_date`; they do not reconstruct historical balances or reverse receipts
recorded after that date. Invoice values and receipt allocations are read in a
single SQL statement. Server organization/entity scope is applied before
recomputing totals; groups without visible items are removed. Existing read
permissions apply to both endpoints, and their nested field projections are
closed.

`credit-exposure` reports limit, exposure, available credit, hold, and customer
status. It validates the customer's currency and is not an FX conversion or a
group-wide consolidated credit calculation.

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
- `GET /aging-by-currency`

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
- distributed AR workers or independently validated production deployment.

Those capabilities require separate migrations, posting and period invariants,
tax controls, integration contracts, and independent security/SoD coverage.
