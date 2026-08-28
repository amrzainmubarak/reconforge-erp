# ADR 0575: Current bounded PostgreSQL HA/DR drill

## Status

Accepted — 2026-08-23

## Context

The repository contained prior dated HA/DR reports. A current execution is
needed before treating the development drill as reproducible evidence.

## Decision

Run `.github/scripts/verify_postgres_ha_dr.py` in a disposable Docker topology
using PostgreSQL 17.10-alpine and record the exact closed report in
`docs/execution/POSTGRES_HA_DR_CURRENT_DRILL_2026-08-23.json`. The run proves
physical synchronous replication, encrypted isolated restore, exact-ID fencing,
zero acknowledged sentinel loss, and bounded failover/failback timing for this
single-host topology.

## Limits

This is one synthetic development run on Docker Engine 29.7.2 with one failure
domain and a manual controller. It does not prove host/zone loss, quorum or
witness behavior, automatic failover, cross-host networking, capacity, a
production RPO/RTO SLO, or enterprise readiness.
