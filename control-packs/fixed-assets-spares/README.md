# Fixed Assets Spares Control Pack

## Target User

Fixed-asset accountants, stores managers, fleet teams, and auditors.

## Business Problem

High-value spares may need capitalization review or stronger equipment traceability.

## Required Input Files

- `stock_moves.csv`
- `work_orders.csv`

## Checks Performed

- High-value spare issue.
- Spare issue missing equipment serial.

## Common Exceptions

- Expensed high-value replacement part.
- Missing asset reference on stock issue.

## Risk Model

High risk for high-value issues, Medium risk for missing asset serial references.

## Recommended Workflow

Run with month-end close and inventory valuation packs.

## Sample Commands

```bash
reconforge rules run --input examples/sample_data --pack control-packs/fixed-assets-spares --output output/rules-fixed-assets
```

## Interpretation Guide

Review capitalization policy before accepting high-value spare expenses.
