# ADR 0264: Bounded PostgreSQL durable-job concurrency parity

- **Status:** Accepted
- **Date:** 2026-08-03

## Decision

Extend the live PostgreSQL durable-job contract with a small concurrent load:
two tenant lanes, three jobs per lane, and two partitions per job. Each lane
uses its own PostgreSQL connection and drains jobs through the existing
claim/checkpoint/complete worker API.

## Evidence boundary

The gate proves only that this declared synthetic workload produces six
completed jobs, twelve unique partition effects, and no duplicate partition
keys under the configured CI PostgreSQL service. It does not establish
capacity, soak, backpressure, queue HA, distributed scale, or production SLOs.

## Reversibility

The change is test and evidence documentation only. Removing the test restores
the previous runtime contract without changing migrations or application code.
