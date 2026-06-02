# Inventory Valuation Control Pack

## Target User

Inventory accountants, ERP consultants, and finance controllers.

## Business Problem

Inventory valuation depends on correct product account mappings, source documents, and sign conventions.

## Required Input Files

- `products.csv`
- `stock_moves.csv`

## Checks Performed

- Missing stock account.
- Missing movement source document.
- Negative quantity with positive value.

## Common Exceptions

- Product category not configured.
- Manual movement without source document.
- Wrong sign convention on adjustment.

## Risk Model

High risk for missing account/source traceability, Medium for sign inconsistencies.

## Recommended Workflow

Run before stock-to-GL reconciliation to catch master-data issues early.

## Sample Commands

```bash
reconforge rules run --input examples/sample_data --pack control-packs/inventory-valuation --output output/rules-inventory-valuation
```

## Interpretation Guide

Treat valuation mapping issues as configuration defects until product/category setup is corrected.
