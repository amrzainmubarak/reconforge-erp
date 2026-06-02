# Fleet Maintenance Control Pack

Use this pack for fleet maintenance companies and internal fleet workshops reviewing repair cost, WIP, and equipment traceability.

Sample command:

```bash
reconforge rules run --input examples/sample_data --pack control-packs/fleet-maintenance --output output/rules-fleet
```

## Risk Model

See `risk_model.yml` for default risk weights and escalation owners.

## Interpretation Guide

Start with Critical and High results, confirm source evidence, assign an owner, and document whether each exception is a true issue, timing difference, mapping issue, or accepted exception.
