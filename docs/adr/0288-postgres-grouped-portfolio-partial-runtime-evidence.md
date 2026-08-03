# ADR 0288: Exercise portfolio partial settlement and fee netting in the PostgreSQL worker

- **Status:** Accepted (bounded E-337 slice)
- **Date:** 2026-08-03
- **Decision owners:** ReconForge maintainers

## Context

The grouped strategy already supported fee-aware netting and explicitly enabled
partial groups inside a non-overlapping portfolio, but the PostgreSQL worker
runtime had only exercised same-currency exact groups and FX conversion. Without
a server-boundary case, the persisted lineage contract for residual balances and
fees could drift from the pure strategy.

## Decision

Extend the live grouped-worker contract with a fourth synthetic portfolio run:

- left `PL1` has gross `120.00` and fee `20.00`, so its net is `100.00`;
- right `PR1` has net `80.00`, yielding an explicitly permitted partial
  settlement of `80.00` and a visible left residual of `20.00`;
- left `PL2` and right `PR2` are exact `50.00`/`50.00` matches;
- `netting_mode: net` and `allow_partial_settlement: true` are persisted in the
  rule and bound into the strategy request digest.

The worker must persist two deterministic edges, retain fee/net/settled/residual
fields in lineage, and expose a portfolio result digest equal to direct strategy
execution.

## Boundary

This is fixed synthetic Decimal data in one PostgreSQL 16 single-node CI
boundary. It does not prove settlement posting, external provider
acknowledgement, statutory accounting, live fees, scale, soak/backpressure,
distributed capacity, HA/DR, or production readiness.

