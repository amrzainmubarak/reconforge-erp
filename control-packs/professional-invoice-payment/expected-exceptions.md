# Expected synthetic exceptions

- `INV-005` is an unmatched invoice with no payment candidate.
- `INV-002` is an amount exception because its payment is USD 10.00 above the invoice.
- `INV-004` is ambiguous because two payments share its reference.
- `PAY-006` is visibly unapplied and is never attached to an invoice.
