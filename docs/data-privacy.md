# Data Privacy

ERP exports often contain sensitive customer, supplier, employee, asset, pricing, invoice, and operational data.

## Do Not Share Live Exports

Avoid sharing live exports in issues, pull requests, public demos, or training material.

## Use Anonymization

Use:

```bash
reconforge anonymize --input live_exports --output anonymized_exports --profile public-demo --mask-amounts
```

## Review Outputs

Generated reports can contain sensitive data from input files. Treat Excel, CSV, JSON, Markdown, HTML, and evidence binder outputs as confidential.

## Data Minimization

Only include columns required for reconciliation and control review. Remove free-text notes unless needed and reviewed.
