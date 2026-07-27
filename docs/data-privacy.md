# Data Privacy

ERP exports often contain sensitive customer, supplier, employee, asset, pricing, invoice, and operational data.

## Do Not Share Live Exports

Avoid sharing live exports in issues, pull requests, public demos, or training material.

## Use Anonymization

Use:

```bash
reconforge anonymize --input live_exports --output anonymized_exports --profile public-demo --mask-amounts
```

Use a new or empty output directory. Default output omits the reversible
original-to-mask table and includes a versioned manifest. If a private mapping
is operationally required, write it with `--private-map-output` to a separate
protected location and never share it with the anonymized folder.

Anonymization is a risk-reduction aid only. Deterministic aliases and amount
noise can be reversible or vulnerable to known-value inference; free text and
unclassified fields can remain identifying.

## Review Outputs

Generated reports can contain sensitive data from input files. Treat Excel, CSV, JSON, Markdown, HTML, and evidence binder outputs as confidential.

## Data Minimization

Only include columns required for reconciliation and control review. Remove free-text notes unless needed and reviewed.
