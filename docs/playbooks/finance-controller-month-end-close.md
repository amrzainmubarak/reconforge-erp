# Finance Controller Month-End Close Playbook

## Target User

Finance controllers, accounting managers, and month-end close owners.

## Problem

Inventory consumption, work-order costs, WIP, and invoices may not agree with GL postings before close. Manual spreadsheets can miss unmatched entries or weak source references.

## Required Data

- `stock_moves.csv`
- `gl_entries.csv`
- `work_orders.csv`
- `invoices.csv`
- `products.csv`

## Commands to Run

```bash
reconforge validate examples/sample_data
reconforge reconcile stock-gl --input examples/sample_data --config config/reconforge.yml --output output
reconforge reconcile workorders --input examples/sample_data --config config/reconforge.yml --output output
reconforge report management-pack --input examples/sample_data --config config/reconforge.yml --output output
reconforge report evidence-binder --input output --output output/evidence
```

## Expected Outputs

- `output/management_pack.xlsx`
- `output/summary.md`
- `output/stock_gl_all_exceptions.csv`
- `output/workorders_all_exceptions.csv`
- `output/evidence/`

## How to Interpret Exceptions

Start with Critical and High items. Prioritize missing GL postings, GL without stock source, material value differences, closed work orders without invoices, and WIP over 90 days.

## Recommended Next Actions

- Ask stores to confirm source documents for unmatched stock issues.
- Ask accounting to validate manual GL entries.
- Ask workshop managers to close or explain stale work orders.
- Attach evidence binder folders to the close review pack where appropriate.

## Common Mistakes

- Reconciling only totals without checking source-document traceability.
- Treating WIP aging as an accounting-only issue.
- Ignoring small repeated mismatches that indicate a systematic mapping problem.
