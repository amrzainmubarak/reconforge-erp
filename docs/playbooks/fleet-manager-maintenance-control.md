# Fleet Manager Maintenance Control Playbook

## Target User

Fleet managers and maintenance supervisors.

## Business Problem

Fleet repairs can repeat on the same equipment, consume parts without old-part returns, or remain in WIP too long.

## Required Data

- `work_orders.csv`
- `stock_moves.csv`
- `old_parts_returns.csv`
- `invoices.csv`

## Command Sequence

```bash
reconforge rules run --input examples/sample_data --pack control-packs/fleet-maintenance --output output/rules-fleet
reconforge report wip-aging --input examples/sample_data --config config/reconforge.yml --output output
```

## Expected Output

Fleet rule results and WIP aging reports.

## How To Read Exceptions

Prioritize repeated equipment repairs, high-cost jobs, missing invoices, and stale WIP.

## Recommended Actions

Investigate recurring failure causes, vendor warranty opportunities, and open work-order closure plans.

## Common Mistakes

- Reviewing parts cost without equipment history.
- Treating repeated repairs as isolated jobs.
- Leaving old WIP open without owner.

## Escalation Path

High-cost repeated repairs should be escalated to fleet operations and finance.
