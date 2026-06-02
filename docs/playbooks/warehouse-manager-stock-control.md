# Warehouse Manager Stock Control Playbook

## Target User

Stores managers, inventory controllers, and spare-parts supervisors.

## Problem

Parts can be issued without valid work orders, fitted directly from purchases, linked to cancelled purchase orders, or missing source documents.

## Required Data

- `stock_moves.csv`
- `purchase_orders.csv`
- `products.csv`
- `old_parts_returns.csv`
- `work_orders.csv`

## Commands to Run

```bash
reconforge validate examples/sample_data
reconforge rules run --input examples/sample_data --pack control-packs/audit-basic --output output/rules
reconforge rules run --input examples/sample_data --pack control-packs/workshop-spare-parts --output output/rules-workshop
reconforge reconcile workorders --input examples/sample_data --config config/reconforge.yml --output output
```

## Expected Outputs

- Rule result CSV/JSON files.
- Work-order exception sheets and CSV files.
- Evidence folders for high-risk exceptions after running the evidence binder.

## How to Interpret Exceptions

Missing product codes and source documents indicate weak transaction traceability. Direct-fit movements and cancelled PO links require immediate review because they affect stock control and supplier payment assurance.

## Recommended Next Actions

- Confirm receipt-before-issue discipline.
- Correct invalid product master references.
- Review direct-fit cases with procurement and workshop teams.
- Follow up old-part return gaps where policy requires returns.

## Common Mistakes

- Accepting verbal explanations without source documents.
- Reviewing warehouse issues without checking the linked work order.
- Treating cancelled PO links as harmless data entry errors.
