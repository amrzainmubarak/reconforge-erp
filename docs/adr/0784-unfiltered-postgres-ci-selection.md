# ADR 0784: Separate PostgreSQL parity and scale-test selection

- Status: Accepted
- Date: 2026-10-03
- Owners: Quality / PostgreSQL

## Context

The live CI command expanded the parity inventory and appended durable-job tests
with one global `-k` expression. Actual collection selected four scale tests and
deselected 380 other tests, including RLS, financial adapters and migrations.

## Decision

Run the advertised general inventory without the scale filter. Exclude the
durable-job module from that expansion and run its four intended scale tests in
a separate command. Explicitly include clean-boot metrics and runtime-role tests.
A regression executes the workflow's inventory producer and actual pytest
collection, comparing every declared module and critical nodes to selected nodes.

## Consequences and rollback

The general gate will run more tests and may expose defects hidden by the old
selection. Collection evidence is not execution evidence; retain both separately.
If CI duration needs tuning, partition explicit modules while preserving coverage.
Reverting the workflow and regression restores the old selection defect and is
not an acceptable substitute for investigating a newly exposed failure.
