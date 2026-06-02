# Odoo Inventory Valuation Control Pack

Use this pack for Odoo implementations where stock moves and valuation layers need to be reviewed against accounting entries.

It checks product account configuration, source-document quality, and sign conventions that commonly affect inventory-to-GL reconciliation.

Sample command:

```bash
reconforge rules run --input examples/sample_data --pack control-packs/odoo-inventory-valuation --output output/rules-odoo
```

## Risk Model

See `risk_model.yml` for default risk weights and escalation owners.

## Interpretation Guide

Start with Critical and High results, confirm source evidence, assign an owner, and document whether each exception is a true issue, timing difference, mapping issue, or accepted exception.
