# Odoo Inventory Valuation Control Pack

This pack supports export-based Odoo inventory valuation review. It helps map Odoo stock, valuation, product, work-order, invoice, and accounting exports into the canonical ReconForge CSV schema, then runs local deterministic controls.

This is not direct Odoo API support and does not require cloud upload. Export Odoo records to CSV/XLSX, map the fields locally, and run ReconForge against the mapped files.

## When To Use

Use this pack when reviewing:

- Stock moves and stock valuation layers against accounting entries.
- Inventory valuation account configuration.
- Product master account setup.
- Work-order or repair/manufacturing references if available.
- Invoice references where stock issues should connect to customer billing.
- Source-document traceability before month-end or audit review.

## Recommended Odoo Exports

| ReconForge file | Odoo source candidates | Notes |
| --- | --- | --- |
| `stock_moves.csv` | `stock.move`, `stock.move.line`, `stock.valuation.layer` | Include movement date, product, quantity, valuation amount, origin/reference, picking, and valuation description. |
| `gl_entries.csv` | `account.move.line` | Include posting date, journal, account, reference, source document, debit, credit, balance/amount, analytic account, and related document. |
| `products.csv` | `product.product`, `product.template`, product category/account fields | Include internal reference, product name, category, standard cost, stock valuation account, and expense account. |
| `work_orders.csv` | `maintenance.request`, `mrp.production`, repair orders, field service orders, or custom workshop model | Use only if the implementation has a stable operational order identifier. |
| `invoices.csv` | `account.move` customer invoices | Include invoice number, related order/work order if available, customer, date, amount, and status. |
| `purchase_orders.csv` | `purchase.order`, `purchase.order.line` | Useful for direct purchase fitting or received-not-invoiced review. |

## Mapping Principles

- Use a consistent `source_document` across stock and accounting lines where possible.
- Prefer Odoo `origin`, `reference`, `picking_id`, valuation layer description, or journal item reference for traceability.
- Use product internal reference as `product_code`.
- Use stock valuation layer value, move value, or signed valuation amount as `total_cost`.
- Use `account.move.line` balance or signed debit/credit value as `amount`.
- Use analytic account, repair order, manufacturing order, or custom field as `work_order` when available.
- Keep all exports to the same accounting period before reconciling.

See `mapping.yml` for field-level candidates.

## Local Workflow

1. Export Odoo records to CSV/XLSX.
2. Map them into ReconForge canonical filenames and columns.
3. Validate the mapped input folder.
4. Run stock-to-GL reconciliation.
5. Validate and run this control pack.
6. Generate reports and evidence binder outputs.

## Commands

```bash
reconforge validate examples/sample_data
reconforge reconcile stock-gl --input examples/sample_data --config config/reconforge.yml --output output/odoo-stock-gl
reconforge mappings validate --pack control-packs/odoo-inventory-valuation
reconforge rules validate --pack control-packs/odoo-inventory-valuation
reconforge rules list --pack control-packs/odoo-inventory-valuation
reconforge rules run --input examples/sample_data --pack control-packs/odoo-inventory-valuation --output output/rules-odoo
reconforge report evidence-binder --input output/odoo-stock-gl --output output/odoo-evidence
```

## Interpretation Guide

Start with high-severity exceptions:

- Missing product stock or expense account.
- Missing source document on stock movement or GL line.
- Stock movement product not found in product master.
- Sign convention mismatches.
- High-value valuation movements needing source evidence.

Classify each exception as true issue, timing difference, mapping issue, accepted risk, or resolved.

## Risk Model

See `risk_model.yml` for default risk weights and escalation owners.
