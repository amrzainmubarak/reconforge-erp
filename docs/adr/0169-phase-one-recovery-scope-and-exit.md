# ADR 0169: Phase 1 recovery scope and exit

## Status

Accepted — 2026-07-28

## Context

P1-PLAT-010 depended on the PostgreSQL contract and object-store foundation but
was recorded as open for Enterprise HA and Regulated air-gap evidence. Those
same outcomes are owned by Phase 3 tasks that depend on P1-PLAT-010, creating a
circular completion condition. Community and Team current-version recovery are
the deployment modes established by the Platform Foundation.

## Decision

The Phase 1 recovery exit covers verified Community SQLite compatibility/current
restores and the current single-node Team PostgreSQL encrypted backup, isolated
restore, integrity, authorization, and rollback path. Enterprise HA, managed
keys, host-loss/failover, measured RPO/RTO, and Regulated air-gap ceremonies
remain explicit Phase 3 gates. The overall recovery matrix remains partial until
those later cells are independently verified.

Record a machine-readable Phase 1 exit audit whose tests bind the normative task
list to completed backlog states, current repository inventories, the unskipped
PostgreSQL gate, and the exact verified/planned recovery cells.

## Consequences

Phase 1 can close without claiming later deployment maturity. P1-PLAT-010 is
complete for its corrected foundation scope, while P3-ENT-009/010/011/012 retain
upgrade, HA/DR, air-gap, and operational evidence. No production readiness,
compliance, certification, or external assurance is implied.
