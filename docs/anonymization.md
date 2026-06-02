# Anonymization

ReconForge ERP includes a local anonymizer so consultants and companies can share safe demo data while preserving reconciliation relationships.

## Command

```bash
reconforge anonymize --input examples/sample_data --output examples/anonymized_data --profile consulting-safe
```

Public demo profile:

```bash
reconforge anonymize --input examples/sample_data --output examples/anonymized_data --profile public-demo --seed 42 --amount-noise-percent 5
```

## What It Masks

Customer, supplier, user, engineer, equipment, invoice, work order, source document, journal, movement, purchase order, and return identifiers.

## Referential Integrity

If `WO-1001` appears in stock moves, GL entries, invoices, and old-part returns, the anonymizer maps it to the same masked value everywhere.

## Amounts and Dates

Use `--mask-amounts` and `--amount-noise-percent` to scale values deterministically. Use `--preserve-dates` when date sequence matters, or `--date-shift-days` to shift dates.

## Security Note

Always review anonymized outputs before sharing. Free-text fields in real ERP exports may contain sensitive data not covered by default schema fields.
