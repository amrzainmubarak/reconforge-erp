# Odoo Export Guide

ReconForge ERP works with Odoo data exported through list views, reporting menus, spreadsheets, or custom export actions. It does not currently provide direct Odoo API support. Export CSV or XLSX files, map them into the canonical ReconForge schema, and run local controls.

## Recommended Odoo Sources

| ReconForge file | Odoo source candidates | Purpose |
| --- | --- | --- |
| `stock_moves.csv` | `stock.move`, `stock.move.line`, `stock.valuation.layer` | Stock movement and valuation review. |
| `gl_entries.csv` | `account.move.line` | Inventory, WIP, expense, variance, and clearing account postings. |
| `work_orders.csv` | `maintenance.request`, `mrp.production`, `repair.order`, field service orders, or custom workshop model | Operational order traceability if available. |
| `purchase_orders.csv` | `purchase.order`, `purchase.order.line` | Purchase and direct fitting review. |
| `products.csv` | `product.product`, `product.template`, `product.category` | Product master and account configuration. |
| `customers.csv` | `res.partner` | Customer reference mapping. |
| `old_parts_returns.csv` | Custom return model, return picking, or service evidence table | Workshop return controls if available. |
| `invoices.csv` | `account.move` customer invoices | Billing and work-order closure review. |

## Field Mapping Notes

| ReconForge field | Odoo field candidates |
| --- | --- |
| `source_document` | `origin`, `reference`, `picking_id`, `move_id/name`, valuation layer description, journal item reference |
| `work_order` | `analytic_account_id`, `repair_id`, `production_id`, `maintenance_request_id`, custom work-order field |
| `product_code` | Product internal reference, `default_code`, external ID |
| `product_name` | Product display name or template name |
| `quantity` | `quantity_done`, `product_uom_qty`, valuation layer quantity |
| `total_cost` | Stock valuation layer value, move value, signed valuation amount |
| `amount` | `account.move.line` balance, signed debit/credit, amount currency where appropriate |
| `account_code` | `account_id/code` |
| `cost_center` | Analytic account or analytic distribution |
| `stock_account` | Product/category stock valuation account |
| `expense_account` | Product/category expense account |

## Practical Export Workflow

1. Choose the accounting period, company, warehouse/plant scope, and account scope.
2. Export stock moves or stock valuation layers.
3. Export account move lines for inventory, WIP, expense, variance, and clearing accounts.
4. Export product master/account configuration.
5. Export work orders, invoices, purchase orders, and customers if those workflows are in scope.
6. Map exports into canonical filenames and columns.
7. Run:

```bash
reconforge validate mapped_odoo_exports
reconforge reconcile stock-gl --input mapped_odoo_exports --config config/reconforge.yml --output output/odoo-stock-gl
reconforge rules validate --pack control-packs/odoo-inventory-valuation
reconforge rules run --input mapped_odoo_exports --pack control-packs/odoo-inventory-valuation --output output/rules-odoo
```

## Common Issues

- Stock valuation layer signs differ from the team's review convention.
- Product internal references are missing or duplicated.
- Account move lines do not include origin, reference, picking, or valuation layer information.
- Work-order identifiers are custom and not present across all files.
- Product/category account configuration differs by company.
- Exported records cover different periods or companies.

## Control Pack

See `control-packs/odoo-inventory-valuation/` for:

- `mapping.yml`
- `rules.yml`
- `expected-exceptions.md`
- `sample-command.md`

Use the control pack as mapping guidance and as a local deterministic rule set after exports are mapped.
