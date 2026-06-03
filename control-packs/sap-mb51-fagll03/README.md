# SAP MB51/FAGLL03 Control Pack

This pack supports export-based SAP material movement and G/L line item review. It helps map MB51 material document exports and FAGLL03/FBL3N G/L line item exports into the canonical ReconForge CSV schema, then runs local deterministic controls.

This is not a SAP connector, not SAP-certified integration, and not a replacement for SAP authorization or controls. It works with local CSV/XLSX exports that users map into ReconForge canonical files.

## When To Use

Use this pack when reviewing:

- MB51 material document movements against FAGLL03 or FBL3N G/L line items.
- Inventory, WIP, variance, expense, or clearing account postings.
- Material-document traceability.
- Posting date and document number alignment.
- Reference, assignment, cost center, material, and movement type quality.

## Recommended SAP Exports

| ReconForge file | SAP export candidates | Notes |
| --- | --- | --- |
| `stock_moves.csv` | MB51 material document list | Include material document, item, posting date, material, quantity, amount/value, plant/storage location, movement type, reference document, order/cost object, and user. |
| `gl_entries.csv` | FAGLL03 or FBL3N G/L line items | Include document number, posting date, G/L account, reference, assignment, document header text, amount, debit/credit, cost center, profit center, order, material if available, and user. |
| `products.csv` | Material master extract | Optional but useful for material master and account determination review. |
| `work_orders.csv` | PM/CS order, internal order, production order, or service order extract | Optional where material issues should trace to work orders or cost objects. |
| `purchase_orders.csv` | ME2N, PO history, or equivalent | Optional for purchase-to-pay and received-not-invoiced review. |
| `invoices.csv` | FI or SD invoice export | Optional for billing traceability. |

## Mapping Principles

- Use SAP posting date as canonical `date`.
- Use MB51 material document or reference document as `source_document`.
- Use FAGLL03/FBL3N document number, reference, assignment, or header text as `reference` or `source_document`.
- Use material number as `product_code`.
- Use movement type as `movement_type`.
- Use cost center, order, WBS, or receiver cost object as `cost_center` or `work_order`, depending on the review objective.
- Use local currency amount or material document value as `amount`/`total_cost`.
- Keep the same company code, plant scope, accounts, and period across exports.

See `mapping.yml` for field-level candidates.

## Local Workflow

1. Export MB51 for the period and movement types under review.
2. Export FAGLL03 or FBL3N for relevant inventory, WIP, variance, expense, or clearing accounts.
3. Map export columns into ReconForge canonical CSV files.
4. Validate the mapped input folder.
5. Run stock-to-GL reconciliation.
6. Validate and run this control pack.
7. Generate management reports and evidence binder outputs.

## Commands

```bash
reconforge validate examples/sample_data
reconforge reconcile stock-gl --input examples/sample_data --config config/reconforge.yml --output output/sap-stock-gl
reconforge mappings validate --pack control-packs/sap-mb51-fagll03
reconforge rules validate --pack control-packs/sap-mb51-fagll03
reconforge rules list --pack control-packs/sap-mb51-fagll03
reconforge rules run --input examples/sample_data --pack control-packs/sap-mb51-fagll03 --output output/rules-sap
reconforge report evidence-binder --input output/sap-stock-gl --output output/sap-evidence
```

## Interpretation Guide

Start with high-severity exceptions:

- GL line missing both reference and source document.
- MB51 movement missing material/product code.
- MB51 movement type missing.
- Material movement product absent from material master export.
- High-value material postings requiring source-document evidence.

Classify each exception as true issue, timing difference, mapping issue, accepted risk, or resolved.

## Risk Model

See `risk_model.yml` for default risk weights and escalation owners.
