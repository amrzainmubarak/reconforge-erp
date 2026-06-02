# Purchase to Pay Control Pack

## Target User

Procurement, stores, finance controllers, and auditors.

## Business Problem

Purchase orders can remain linked to operational activity after cancellation or can support high-value direct purchases without enough evidence.

## Required Input Files

- `purchase_orders.csv`
- `work_orders.csv`

## Checks Performed

- Cancelled purchase orders linked to work orders.
- High-value purchase order review threshold.

## Common Exceptions

- Cancelled PO still referenced by workshop activity.
- Large PO without clear receipt or issue trail.

## Risk Model

Cancelled linked POs are Critical. High-value POs are Medium unless other controls fail.

## Recommended Workflow

Run with workshop and inventory packs during month-end procurement review.

## Sample Commands

```bash
reconforge rules run --input examples/sample_data --pack control-packs/purchase-to-pay --output output/rules-p2p
```

## Interpretation Guide

Cancelled PO exceptions need procurement and finance sign-off before payment or cost recognition.
