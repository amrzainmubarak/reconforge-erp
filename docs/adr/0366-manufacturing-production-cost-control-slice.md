# ADR 0366: Add an export-based manufacturing production-cost control slice

- **Date:** 2026-08-05
- **Status:** Accepted for the experimental Phase 4 breadth track

## Decision

Add a bounded `manufacturing.cost-control` module that compares local
production-order, material-issue, completion, and scrap exports. The module uses
exact `Money` and `Quantity`, one-currency/unit policies, standard/material and
completion-cost variance, planned-versus-completed quantity, scrap limits,
unknown-order lineage, deterministic ordering, source fingerprints, and a
digest-bound report.

The first interface is a non-posting CLI/library slice. It does not authenticate
an ERP/MRP source, connect to a provider, calculate statutory or approved
standard-cost valuation, post inventory/WIP/GL entries, or write back.

## Verification and rollback

The slice is covered by `tests/test_manufacturing_cost_control.py`, module and
threat-model parity tests, the declarative pack, and the full local gates recorded
as E-439/E-440. Rollback is removal of the module, CLI wiring, fixtures, pack,
schema, registry entry, docs, and tests in one reviewed commit.

## Explicit non-goals

Live ERP/MRP connectors, statutory valuation, inventory/WIP/GL posting, write-back,
persistence/API/Studio, HA/DR, provider interoperability, and production
availability remain separate gates requiring their own evidence.
