# Manufacturing Production Cost Controls

This experimental pack checks exported production-order, material-issue,
completion, and scrap records. It is intended for manufacturing and WIP review
beside the source ERP.

It does not post inventory, WIP, or GL entries; calculate statutory cost; approve
standard-cost policy; or connect to an ERP. Use the typed local command for the
exact cross-file arithmetic control:

```bash
reconforge manufacturing cost-control run \
  --orders-input examples/manufacturing_cost_control/orders.json \
  --issues-input examples/manufacturing_cost_control/issues.json \
  --completions-input examples/manufacturing_cost_control/completions.json \
  --scrap-input examples/manufacturing_cost_control/scrap.json \
  --currency EUR --tolerance 0.01 --max-scrap-quantity 5
```
