# Odoo Consultant Implementation Playbook

## Target User

Odoo implementers, functional consultants, and finance-system advisors.

## Problem

During or after implementation, Odoo stock valuation and accounting behavior may not align with customer expectations, custom work-order flows, or legacy reporting.

## Required Data

- Odoo `stock.move` or equivalent mapped to `stock_moves.csv`
- Odoo `account.move.line` mapped to `gl_entries.csv`
- Product master mapped to `products.csv`
- Work orders, field service jobs, or maintenance requests mapped to `work_orders.csv`

## Commands to Run

```bash
reconforge validate mapped_odoo_exports
reconforge rules run --input mapped_odoo_exports --pack control-packs/odoo-inventory-valuation --output output/odoo-rules
reconforge reconcile stock-gl --input mapped_odoo_exports --config config/reconforge.yml --output output
```

## Expected Outputs

- Validation errors for mapping gaps.
- Rule results for product accounts, valuation source references, and value signs.
- Stock/GL reconciliation outputs.

## How to Interpret Exceptions

Missing stock or expense accounts often indicate product-category configuration gaps. Source-document and valuation mismatches often indicate mapping or posting-flow differences.

## Recommended Next Actions

- Confirm product-category accounting settings.
- Normalize source document and reference fields.
- Compare Odoo valuation layers to GL lines for sample transactions.
- Agree a close review workflow with the finance team.

## Common Mistakes

- Exporting display names without stable IDs.
- Losing the work-order reference during mapping.
- Treating Odoo bank/account reconciliation as sufficient for inventory-to-GL control.
