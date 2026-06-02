# Month-End Close Control Pack

## Target User

Finance controllers and accounting managers.

## Business Problem

Close readiness depends on stale WIP review and manual journal evidence.

## Required Input Files

- `work_orders.csv`
- `gl_entries.csv`

## Checks Performed

- Open WIP older than 90 days.
- Manual journal entries requiring review.

## Common Exceptions

- Long-open jobs without closure plan.
- Manual spare-parts expense entries.

## Risk Model

Old WIP is High risk. Manual journals are Medium risk unless unsupported by evidence.

## Recommended Workflow

Run during pre-close review and attach exceptions to the close pack.

## Sample Commands

```bash
reconforge rules run --input examples/sample_data --pack control-packs/month-end-close --output output/rules-close
```

## Interpretation Guide

Every old WIP item should have an owner, reason, and expected resolution date.
