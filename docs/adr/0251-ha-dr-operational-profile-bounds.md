# ADR 0251: Bind HA/DR targets to bounded drill evidence

- **Status:** Accepted
- **Date:** 2026-08-03

## Decision

Publish a schema-validated operational profile for the retained three-run
PostgreSQL synchronous-standby drill. The profile declares zero acknowledged
transaction loss and a 60-second failover/failback ceiling, preserves the
operator runbook, and links directly to the source report.

## Boundary

The profile is `partial`. It describes one Docker host and a manual controller;
it does not prove host/zone/region loss, quorum or witness fencing, automatic
failover, production key custody, or production SLOs.

## Reversibility

The profile and schema are additive evidence artifacts and can be removed
without changing runtime, migration, or deployment behavior.
