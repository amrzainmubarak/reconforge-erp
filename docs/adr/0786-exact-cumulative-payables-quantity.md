# ADR 0786: Conserve received quantity across AP approvals

- Status: Accepted
- Date: 2026-10-03
- Owners: Financial Integrity / Payables

## Context

Two invoices could independently pass matching against the same receipt and both
be approved. Duplicate references to one PO line bypassed a per-line comparison.
Decimal normalize and arithmetic inherited caller precision, silently rounding
persisted quantities. Re-matching an approved invoice could release its quantity
consumption by changing its status.

## Decision

Use shared exact quantity text, sums and products independent of Decimal
precision. Aggregate repeated PO-line references before comparing proposed
quantities with min(ordered, received) less Approved/Paid consumption. Partial
invoices may pass when quantity remains available; a negative quantity variance
means proposed quantity is below remaining capacity. Price and total checks
remain exact.

Recheck capacity at approval under the same parent lock as matching and receipts.
SQLite uses a writer transaction. PostgreSQL locks the PO FOR NO KEY UPDATE,
compatible with child foreign-key checks, and rereads state after acquiring it.
Approved/Paid invoices cannot reenter matching. Preserve version checks, maker/
checker, atomic audit and outbox behavior.

## Verification and rollback

Independent connections race approvals and receipts on both adapters. Regression
coverage includes duplicate line references, partial consumption, low Decimal
precision, legacy Matched invoices, immutable approved state, and audit/outbox
failure rollback. A Fraction-based property oracle checks arithmetic.

No data migration is needed. Existing over-approved documents are retained and
require review; the fix does not rewrite historical financial evidence. A source
rollback removes these guards and must not reopen concurrent approvals without
an alternative verified conservation control.
