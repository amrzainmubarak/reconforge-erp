# Manufacturing Controller WIP Review Playbook

## Target User

Manufacturing controllers, cost accountants, and production managers.

## Business Problem

Material issues, production orders, and WIP balances may not close cleanly, causing valuation and margin risk.

## Required Data

- `work_orders.csv`
- `stock_moves.csv`
- `gl_entries.csv`
- `products.csv`

## Command Sequence

```bash
reconforge rules run --input examples/sample_data --pack control-packs/manufacturing-wip --output output/rules-manufacturing
reconforge reconcile stock-gl --input examples/sample_data --config config/reconforge.yml --output output
```

## Expected Output

Manufacturing WIP rule results, stock/GL exceptions, and management pack.

## How To Read Exceptions

Focus on old WIP, material issued without valid order, and cost variance.

## Recommended Actions

Confirm production completion, scrap/rework treatment, variance explanation, and GL posting accuracy.

## Common Mistakes

- Reconciling only GL balances.
- Ignoring production order status.
- Treating material issue timing differences as permanent errors.

## Escalation Path

Old high-value WIP should be escalated to manufacturing finance leadership.
