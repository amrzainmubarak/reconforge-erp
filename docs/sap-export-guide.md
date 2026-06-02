# SAP Export Guide

ReconForge ERP supports SAP-style reconciliation workflows using exported files. It is not a SAP connector; it consumes CSV or XLSX exports shaped into the ReconForge schema.

## Common SAP Sources

| ReconForge File | SAP Source |
| --- | --- |
| `stock_moves.csv` | MB51 material document list |
| `gl_entries.csv` | FAGLL03 or FBL3N GL line items |
| `work_orders.csv` | PM/CS order list, service order list, or workshop order extract |
| `purchase_orders.csv` | ME2N, purchase order history, or equivalent |
| `products.csv` | Material master extract |
| `customers.csv` | Customer master or service customer extract |
| `invoices.csv` | Billing or FI customer invoice extract |

## Mapping Notes

- Use material document, reference document, or assignment as `source_document`.
- Use GL line item reference or assignment as `reference`.
- Use order number, cost object, or internal order as `work_order`.
- Use posting date as `date`.
- Use local currency amount as `amount`.
- Use movement value or material document value as `total_cost`.

## MB51 vs FAGLL03/FBL3N Workflow

1. Export MB51 movements for the period and relevant movement types.
2. Export FAGLL03 or FBL3N for inventory expense, WIP, and variance accounts.
3. Map both exports into ReconForge schema.
4. Run `reconforge reconcile stock-gl`.
5. Investigate unmatched records, value differences, date differences, and weak-reference matches.

## Audit Use

SAP references may vary by configuration and posting process. ReconForge's fuzzy and proximity levels help identify likely matches, but finance teams should use the exception sheets to document final explanations and adjustments.
