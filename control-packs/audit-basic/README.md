# Audit Basic Control Pack

Use this pack when you need a quick ERP export health review before finance, stores, workshop, or audit teams spend time on detailed reconciliation.

## Required Input Files

- `stock_moves.csv`
- `gl_entries.csv`

## Controls

- Missing source document
- Missing work order on stock issue
- Missing product code
- Invalid negative stock amount
- Missing GL account code
- High-value stock issue review threshold
- Missing GL reference
- Source-document pattern risk

## Recommended Workflow

```bash
reconforge rules validate --pack control-packs/audit-basic
reconforge rules run --input examples/sample_data --pack control-packs/audit-basic --output output/rules
```

Review `output/rules/rule_results.csv` before running the management pack.

## Risk Model

See `risk_model.yml` for default risk weights and escalation owners.

## Interpretation Guide

Start with Critical and High results, confirm source evidence, assign an owner, and document whether each exception is a true issue, timing difference, mapping issue, or accepted exception.
