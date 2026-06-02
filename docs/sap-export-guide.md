# SAP Export Guide

ReconForge ERP supports SAP-style reconciliation workflows using exported files. It is not a SAP connector. It consumes CSV or XLSX exports shaped into the ReconForge canonical schema.

## Common SAP Sources

| ReconForge file | SAP export candidates | Purpose |
| --- | --- | --- |
| `stock_moves.csv` | MB51 material document list | Material movement and valuation traceability. |
| `gl_entries.csv` | FAGLL03 or FBL3N G/L line items | Inventory, WIP, variance, expense, and clearing account review. |
| `work_orders.csv` | PM/CS order list, production order list, internal order list, or service order extract | Work-order or cost-object traceability. |
| `purchase_orders.csv` | ME2N, purchase order history, or equivalent | Purchase and received-not-invoiced review. |
| `products.csv` | Material master extract | Material master and valuation/account review. |
| `customers.csv` | Customer master or service customer extract | Customer reference mapping if needed. |
| `invoices.csv` | Billing or FI customer invoice extract | Billing traceability if needed. |

## Field Mapping Notes

| ReconForge field | SAP field candidates |
| --- | --- |
| `date` | Posting date, `BUDAT` |
| `source_document` | Material document, reference document, document number, `AWKEY`, assignment |
| `reference` | Reference, assignment, document header text, document number |
| `product_code` | Material number, `MATNR` |
| `product_name` | Material description |
| `movement_type` | Movement type, `BWART` |
| `quantity` | Quantity, entry quantity |
| `total_cost` | Material document value or local currency amount |
| `amount` | Amount in local currency, signed amount |
| `account_code` | G/L account |
| `cost_center` | Cost center, profit center, order, WBS, receiver cost object |
| `work_order` | PM order, CS order, production order, internal order, WBS |
| `created_by` | User name or SAP user |

## MB51 vs FAGLL03/FBL3N Workflow

1. Export MB51 movements for the period, company code/plant scope, and relevant movement types.
2. Export FAGLL03 or FBL3N for inventory, WIP, variance, expense, and clearing accounts.
3. Confirm both exports use consistent posting date ranges and company code scope.
4. Map both exports into ReconForge canonical files.
5. Run:

```bash
reconforge validate mapped_sap_exports
reconforge reconcile stock-gl --input mapped_sap_exports --config config/reconforge.yml --output output/sap-stock-gl
reconforge rules validate --pack control-packs/sap-mb51-fagll03
reconforge rules run --input mapped_sap_exports --pack control-packs/sap-mb51-fagll03 --output output/rules-sap
```

## Common Issues

- GL export layout omits assignment, reference, material document, or header text.
- MB51 export omits movement type or material number.
- Cost center/order/WBS fields are not included in the GL layout.
- Amount sign conventions differ between MB51 and FI reports.
- Movement type scope does not match the accounts being reviewed.
- Exports cover different posting periods.

## Audit Use

ReconForge matching can identify exact and likely matches, but reviewers must document final explanations and adjustments. Use evidence outputs to classify exceptions as true issue, timing difference, mapping issue, accepted risk, or resolved.

## Control Pack

See `control-packs/sap-mb51-fagll03/` for:

- `mapping.yml`
- `rules.yml`
- `expected-exceptions.md`
- `sample-command.md`

Use the control pack as export mapping guidance and a local deterministic rule set after SAP exports are mapped.
