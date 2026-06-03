# Synthetic Case Study: Odoo Stock Valuation Pilot

This is a synthetic case study and illustrative scenario based on sample data. It does not describe a real customer, real savings, or a completed audit.

## Scenario

A mid-market spare-parts distributor uses Odoo-style exports for stock moves, valuation layers, products, invoices, and account move lines. The finance controller wants a local pilot to test whether export-based reconciliation can identify traceability and valuation-control gaps before month-end review.

## Data Inputs

- `stock_moves.csv`
- `gl_entries.csv`
- `products.csv`
- `work_orders.csv`
- `purchase_orders.csv`
- `invoices.csv`

## Commands Used

```bash
reconforge validate examples/sample_data
reconforge mappings validate --pack control-packs/odoo-inventory-valuation
reconforge mappings wizard --input examples/sample_data --pack control-packs/odoo-inventory-valuation --output output/odoo_mapping
reconforge demo run --output output/demo
reconforge report client-pack --input output/demo --output output/client_pack --redact-names --exclude-raw-records --include-manifest-checksums
```

## Sample Findings

- Stock movements requiring GL traceability review.
- Products needing account-configuration checks.
- High-value movement evidence cases requiring reviewer notes.
- Exceptions moved from `New` to `Under Review` in the local review workflow.

## Outputs Generated

- Management pack workbook.
- Executive report.
- Dashboard.
- Evidence binder.
- Review register.
- Client handoff pack with privacy note and manifest.

## Recommendations

- Confirm Odoo export period, company, and account scope.
- Review missing source-document exceptions first.
- Separate mapping issues from true posting issues.
- Re-run after corrected exports.

## What This Proves

The workflow can run locally against mapped Odoo-style exports and produce reviewable outputs.

## What This Does Not Prove

- It does not prove live Odoo integration.
- It does not prove savings.
- It does not issue an audit opinion.
- It does not certify accounting configuration.
