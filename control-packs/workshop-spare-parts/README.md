# Workshop Spare Parts Control Pack

Use this pack for service centers, dealership workshops, and maintenance operations where stores issues must be traceable to work orders and old-part return evidence.

Sample command:

```bash
reconforge rules run --input examples/sample_data --pack control-packs/workshop-spare-parts --output output/rules-workshop
```

## Risk Model

See `risk_model.yml` for default risk weights and escalation owners.

## Interpretation Guide

Start with Critical and High results, confirm source evidence, assign an owner, and document whether each exception is a true issue, timing difference, mapping issue, or accepted exception.
