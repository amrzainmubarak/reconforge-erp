# ADR 0286: Exercise true many-to-many matching in the PostgreSQL worker

- **Status:** Accepted (bounded E-335 slice)
- **Date:** 2026-08-03
- **Decision owners:** ReconForge maintainers

## Context

The PostgreSQL grouped worker already had a live one-to-many and crash/resume
contract. The pure strategy supports true many-to-many, but the hosted worker
projection had not exercised its Cartesian group lineage against PostgreSQL.

## Decision

Extend the existing live grouped-worker test with a second synthetic run using
two left records and two right records under explicit `many-to-many` mode. The
worker must complete both runs, persist four deterministic Cartesian edges,
retain the grouped mode and decision digest in lineage, and match the direct
strategy digest. The original one-to-many assertions remain unchanged.

## Boundary

This is one small PostgreSQL 16 single-node worker cycle under the
non-superuser RLS role. It does not establish 10K/100K/1M PostgreSQL scale,
soak/backpressure, distributed capacity, process supervision, HA/DR, posting,
or write-back.
