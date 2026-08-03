# ADR 0289: Exercise same-tenant durable-job claim contention in PostgreSQL

- **Status:** Accepted (bounded E-338 slice)
- **Date:** 2026-08-03
- **Decision owners:** ReconForge maintainers

## Context

The PostgreSQL durable-job runtime already had a two-tenant load and retry
contract, but its worker load used one worker lane per tenant. That left the
`FOR UPDATE SKIP LOCKED` ownership boundary under same-tenant contention
unexercised.

## Decision

Extend the existing live PostgreSQL job contract with four synthetic jobs for
one tenant, each containing three partitions, and drain the shared queue with
two independent worker connections. Each worker repeatedly claims the next
available job, commits its checkpointed prefix, and completes the final
partition. The gate requires every job to reach `completed`, exactly three
unique partition effects per job, and the sum of worker completions to equal
the declared workload.

## Boundary

This is a small PostgreSQL 16 single-node contention test. It proves claim
ownership and no-duplicate effects for this shape only; it does not establish
capacity, throughput, fairness SLOs, soak behavior, distributed supervision,
queue HA, automatic failover, or production readiness.

