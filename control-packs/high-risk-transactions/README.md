# High Risk Transactions Pack

## Target User

Internal auditors, finance controllers, and inventory accountants.

## Business Problem

High-value and backdated transactions require stronger evidence during close and audit review.

## Required Input Files

- `stock_moves.csv`
- `gl_entries.csv`

## Checks Performed

- High-value stock movements.
- Backdated stock movements.

## Common Exceptions

- Large issue to a work order.
- Transaction posted outside expected period.

## Risk Model

High-value activity is High risk; backdated activity is Medium unless paired with missing evidence.

## Recommended Workflow

Run after validation and before evidence binder generation.

## Sample Commands

```bash
reconforge rules run --input examples/sample_data --pack control-packs/high-risk-transactions --output output/rules-high-risk
```

## Interpretation Guide

High-value transactions should be sampled for approval, source evidence, and GL traceability.
