# Governed service sales

The `/sales-revenue` Studio workflow uses a configured PostgreSQL server and its canonical organization, workspace, legal entity, customers, fiscal periods, accounts and journals. It records service revenue; it does not create stock movements.

Create an active customer through the existing Accounts Receivable customer form, or load an existing customer. Define one to sixteen services with exact quantity text, integer minor-unit prices and integer discount basis points. The explicit policy rounds the discounted unit price HALF_UP to minor units, then rounds quantity × net unit price HALF_UP. The quotation preserves gross price, discount, net price, line totals, currency-policy metadata and digest. Tax is zero in this bounded workflow.

The maker submits the quotation. A different current human approves terms and discounts. Record the customer's accepted order reference inside quotation validity, then the genuine service completion reference and business date. Fulfillment cannot precede the quotation date.

Prepare the invoice using the current open fiscal period, functional-currency journal, Asset receivable account and Income revenue account. The native AR invoice is submitted and the two-line GL draft is captured in the same transaction. An independent reviewer approves the native customer credit exposure and validates the exact GL snapshot. A poster different from the preparer publishes the retained effect. Failed financial participants roll back the enclosing sales command.

Prepare full collection only for the completely unpaid invoice. Capture a receipt number, date, cash journal and Asset cash account. The independent reviewer validates the pending cash/AR effect. The poster then creates the actual native AR receipt and its one full allocation, publishes the reviewed cash/AR GL and advances the sale to Paid within one outer ACID transaction. No Posted receipt or Paid allocation is exposed by preparation or review.

Use the retained command after any lost response or 5xx. Its actor, selected scope, expected version, reason, route and nested financial request remain frozen in browser memory. A modified command identifier, actor or content is rejected. Refresh current state after a known rejection. Current persisted authority is checked before recovery.

Every version retains one immutable command, event and audit reference. PostgreSQL guards verify quotation pricing/digest, selected scope, source ancestry, review and final native AR/GL closure. Direct history mutations and incomplete stage publication fail. A populated downgrade refuses to discard these sources. Before upgrading, preserve a verified backup; rollback a populated deployment through its reviewed restore procedure.

Stock delivery, cost-of-sales, service credits, refunds, partial collection, taxes and foreign-currency settlement require separate completed workflows. Their absence is shown in the interface and manifest. The module remains experimental pending the integrated native/API/browser/restore gates.
