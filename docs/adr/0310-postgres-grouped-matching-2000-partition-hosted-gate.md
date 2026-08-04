# ADR 0310: Run the grouped-matching 2,000-partition tier as a hosted gate

- Status: accepted
- Date: 2026-08-04
- Scope: bounded PostgreSQL advanced-matching runtime evidence

## Context

ReconForge already has domain-diverse 10K grouped-matching evidence on one
host and a small live PostgreSQL worker/scale contract. The PostgreSQL gate did
not yet exercise the grouped modes over a materially larger concurrent
partition set.

## Decision

Extend the hosted `server-boundaries` matrix with
`test_live_postgres_grouped_matching_2000_partition_scale_profile`. The test
reuses the existing PostgreSQL repository, RLS boundary, checkpoint worker,
and public grouped-strategy adapter with 16 worker connections, 1,000 runs,
two partitions per run, five declared modes, and a bounded batch size of 16.

## Evidence boundary

The gate requires 2,000 completed partitions, exact result-row cardinality,
zero duplicate result identities, zero failed or active runs, and 200 runs per
mode. It is hosted single-node synthetic PostgreSQL correctness/concurrency
evidence. It does not establish throughput capacity, soak behavior, queue
backpressure, cross-host scheduling, provider interoperability, statutory
posting, write-back, HA/DR, or production sizing.

## Rollback

Remove the explicit test invocation, this ADR, its manifest entry, and the
workflow contract assertion. Retain the existing 64-partition and local
domain-diverse evidence.
