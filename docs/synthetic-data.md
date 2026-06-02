# Synthetic Data Lab

The synthetic data generator creates local ERP-like datasets for demos, testing, benchmarking, and rule-pack development.

## Command

```bash
reconforge generate synthetic --rows 1000 --industry workshop --exception-rate 0.15 --critical-rate 0.05 --seed 42 --currency SAR --output benchmarks/small_1k
```

Supported industries:

- `workshop`
- `manufacturing`
- `fleet`
- `dealership`
- `service`

## Generated Files

- `stock_moves.csv`
- `gl_entries.csv`
- `work_orders.csv`
- `purchase_orders.csv`
- `products.csv`
- `customers.csv`
- `old_parts_returns.csv`
- `invoices.csv`

## Scenario Patterns

The generator creates exact matches, fuzzy matches, unmatched stock, unmatched GL, amount mismatches, date mismatches, duplicate references, direct purchase fitting, missing old-part returns, WIP aging, closed jobs without invoices, cancelled PO linkage, and manual entries.
