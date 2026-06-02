# Service Contracts Control Pack

## Target User

Service managers, finance controllers, and contract administrators.

## Business Problem

Service jobs can be completed without billing evidence or can consume costs beyond contract coverage.

## Required Input Files

- `work_orders.csv`
- `invoices.csv`

## Checks Performed

- Closed service jobs missing invoices.
- High-cost contract-like service jobs.

## Common Exceptions

- Work completed but invoice not posted.
- Contract job cost exceeds expected coverage.

## Risk Model

High risk is assigned to missing billing evidence. Medium risk is assigned to high-cost contract jobs requiring margin review.

## Recommended Workflow

Run this pack after work-order reconciliation and before month-end billing review.

## Sample Commands

```bash
reconforge rules run --input examples/sample_data --pack control-packs/service-contracts --output output/rules-service-contracts
```

## Interpretation Guide

Treat missing invoice exceptions as billing completeness issues until finance or service management documents a valid reason.
