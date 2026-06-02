# Dealership Service Control Pack

Use this pack for dealership workshops and service centers that need job-card, parts, old-part return, and invoice controls.

Sample command:

```bash
reconforge rules run --input examples/sample_data --pack control-packs/dealership-service --output output/rules-dealership
```

## Risk Model

See `risk_model.yml` for default risk weights and escalation owners.

## Interpretation Guide

Start with Critical and High results, confirm source evidence, assign an owner, and document whether each exception is a true issue, timing difference, mapping issue, or accepted exception.
