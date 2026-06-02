# Manufacturing WIP Control Pack

Use this pack for manufacturers reviewing material issues, production orders, WIP balances, and cost variance.

Sample command:

```bash
reconforge rules run --input examples/sample_data --pack control-packs/manufacturing-wip --output output/rules-manufacturing
```

## Risk Model

See `risk_model.yml` for default risk weights and escalation owners.

## Interpretation Guide

Start with Critical and High results, confirm source evidence, assign an owner, and document whether each exception is a true issue, timing difference, mapping issue, or accepted exception.
