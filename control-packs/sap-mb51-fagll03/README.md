# SAP MB51/FAGLL03 Control Pack

Use this pack when SAP users export MB51 material movements and FAGLL03/FBL3N G/L line items for period-end reconciliation.

Controls focus on missing reference keys, high-value GL lines, and export quality needed for material-document matching.

Sample command:

```bash
reconforge rules run --input examples/sample_data --pack control-packs/sap-mb51-fagll03 --output output/rules-sap
```

## Risk Model

See `risk_model.yml` for default risk weights and escalation owners.

## Interpretation Guide

Start with Critical and High results, confirm source evidence, assign an owner, and document whether each exception is a true issue, timing difference, mapping issue, or accepted exception.
