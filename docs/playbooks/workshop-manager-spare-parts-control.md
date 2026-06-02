# Workshop Manager Spare-Parts Control Playbook

## Target User

Workshop managers, service managers, dealership service leads, and fleet maintenance supervisors.

## Problem

Work orders may consume parts without clean closure, invoice, old-part return, or accounting traceability.

## Required Data

- `work_orders.csv`
- `stock_moves.csv`
- `old_parts_returns.csv`
- `invoices.csv`
- `purchase_orders.csv`

## Commands to Run

```bash
reconforge reconcile workorders --input examples/sample_data --config config/reconforge.yml --output output
reconforge report wip-aging --input examples/sample_data --config config/reconforge.yml --output output
reconforge rules run --input examples/sample_data --pack control-packs/workshop-spare-parts --output output/rules-workshop
```

## Expected Outputs

- `output/workorder_reconciliation.xlsx`
- `output/wip_aging.xlsx`
- Rule results for spare-part controls.

## How to Interpret Exceptions

Focus on closed work orders with pending stock movement, old WIP, missing invoices, direct purchase fitting, and missing old-part returns.

## Recommended Next Actions

- Close or explain old open jobs.
- Confirm invoices for completed billable work.
- Document warranty or internal jobs separately.
- Return old parts or record approved exceptions.

## Common Mistakes

- Closing the operational job without checking financial closure.
- Issuing parts after invoice or closure without reopening the job.
- Ignoring repeated repair patterns on the same equipment.
