# Multi-Warehouse Controls Pack

## Target User

Inventory controllers, warehouse managers, and ERP consultants.

## Business Problem

Warehouse attribution and source-document uniqueness are essential for multi-location stock control.

## Required Input Files

- `stock_moves.csv`

## Checks Performed

- Missing warehouse.
- Duplicate stock source document.

## Common Exceptions

- Movement exported without location.
- Duplicate source document across split or repeated movement.

## Risk Model

Missing warehouse is High risk. Duplicate reference is Medium until confirmed as valid split.

## Recommended Workflow

Run before multi-warehouse stock valuation or transfer review.

## Sample Commands

```bash
reconforge rules run --input examples/sample_data --pack control-packs/multi-warehouse-controls --output output/rules-warehouse
```

## Interpretation Guide

Duplicate documents should be reconciled to quantities and GL impact before acceptance.
