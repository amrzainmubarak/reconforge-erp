# ADR 0249: Verify governed job authorization with the PostgreSQL adapter

- **Status:** Accepted
- **Date:** 2026-08-03

## Decision

Exercise `GovernedDurableJobApplicationService` over the real PostgreSQL
durable-job repository in the non-privileged server-boundaries contract. The
test must prove a denied permission reaches no repository row, an allowed
tenant/workspace-scoped submit creates one row, and a sibling tenant cannot
observe it.

## Boundary

This promotes only the wrapper-plus-repository runtime path. It does not imply
that every API, export, scheduler, worker, federation, or cache path has been
migrated, and it does not add HA/DR or multi-host evidence.

## Reversibility

The change is test and inventory evidence only; removing the test and reverting
the inventory status restores the prior bounded claim without a schema change.
