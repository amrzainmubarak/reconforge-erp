# Professional Invoice and Payment Controls

This experimental pack checks exported professional-service invoices and client
payments beside the source billing or accounting system. It keeps unmatched,
duplicate, ambiguous, and unapplied cash visible.

The typed local control is non-posting and provider-neutral:

```bash
reconforge professional invoice-payment run \
  --invoices-input examples/professional_invoice_payment/invoices.json \
  --payments-input examples/professional_invoice_payment/payments.json \
  --currency USD --tolerance 0.01 --payment-window-days 7
```

It does not approve revenue, allocate receivables, post a journal, connect to a
live billing provider, or write back to an ERP.
