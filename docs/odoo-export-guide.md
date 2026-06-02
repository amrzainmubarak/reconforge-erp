# Odoo Export Guide

ReconForge ERP can work with Odoo data exported through list views, reporting menus, or custom export actions. Export CSV or XLSX files and map them to the canonical sample schema.

## Recommended Odoo Sources

| ReconForge File | Odoo Source |
| --- | --- |
| `stock_moves.csv` | `stock.move`, `stock.move.line`, or `stock.valuation.layer` |
| `gl_entries.csv` | `account.move.line` |
| `work_orders.csv` | `maintenance.request`, field service orders, manufacturing repair orders, or a custom workshop model |
| `purchase_orders.csv` | `purchase.order` and `purchase.order.line` |
| `products.csv` | `product.product` and `product.template` |
| `customers.csv` | `res.partner` |
| `old_parts_returns.csv` | Custom return model, stock return picking, or service evidence table |
| `invoices.csv` | `account.move` customer invoices |

## Mapping Notes

- Use Odoo `origin`, `reference`, `picking_id`, or valuation layer description as `source_document`.
- Use `analytic_account_id`, custom work-order field, or repair order number as `work_order`.
- Use inventory valuation amount or issue value as `total_cost`.
- Use posted `account.move.line` debit or credit value as `amount`.
- Export product internal reference as `product_code`.
- Export customer external ID or reference as `customer_code` where possible.

## Practical Controls

Odoo implementations often customize workshop flows. The safest approach is to map the operational work-order identifier consistently across stock, purchase, invoice, and accounting records before running reconciliation.
