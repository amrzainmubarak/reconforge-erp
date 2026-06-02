# SAP User Export Reconciliation Playbook

## Target User

SAP finance users, inventory accountants, auditors, and consultants working with MB51 and FAGLL03/FBL3N extracts.

## Problem

SAP logistics and accounting reports are powerful, but many teams still reconcile MB51 material movements to G/L line items manually in Excel.

## Required Data

- MB51-style material movement export mapped to `stock_moves.csv`
- FAGLL03 or FBL3N-style G/L line item export mapped to `gl_entries.csv`
- Work orders or internal orders where relevant
- Product/material master mapping where available

## Commands to Run

```bash
reconforge validate sap_mapped_exports
reconforge rules run --input sap_mapped_exports --pack control-packs/sap-mb51-fagll03 --output output/sap-rules
reconforge reconcile stock-gl --input sap_mapped_exports --config config/reconforge.yml --output output
```

## Expected Outputs

- Rule results for missing reference keys, amount mismatch risks, date mismatch risks, and cost-center gaps.
- Stock/GL reconciliation exception files.
- Management pack for audit review.

## How to Interpret Exceptions

Start with GL expense lines that do not point back to a material document, material movements without GL impact, and cost-center or posting-date differences.

## Recommended Next Actions

- Confirm which SAP fields represent material document, assignment, reference, work order, and cost center.
- Normalize reference keys before matching.
- Separate timing differences from permanent mismatches.
- Use evidence binder cases for audit support.

## Common Mistakes

- Comparing only summarized balances.
- Ignoring sign conventions between material movement values and GL debit/credit.
- Using unstable text descriptions instead of document numbers where possible.
