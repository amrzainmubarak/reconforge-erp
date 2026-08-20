# ADR 0443: Exercise persistent scheduler cursor contention with independent SQLite connections

## Status

Accepted as bounded local concurrency evidence; PostgreSQL and cross-host
fairness remain separate gates.

## Context

ADR 0442 proved that a scheduler restart continues a persisted lane sequence,
but a restart test alone does not exercise transaction contention. SQLite
durable jobs use `BEGIN IMMEDIATE` and a bounded busy timeout, so two worker
loops must serialize cursor reservations without losing or duplicating an
index.

## Decision

Run two independent SQLite connections in separate executor threads against
the same migrated database and scheduler key. Each connection reserves six
lanes. The contract requires twelve committed reservations, six selections
for each of two lanes, and a final cursor version of twelve at index zero.
Connections are created and closed inside their owning worker threads.

## Evidence and boundary

The contention test is synthetic local SQLite evidence of transaction-level
serialization. It does not establish PostgreSQL lock behavior, cross-host
fairness, throughput, queue HA/failover, soak, capacity, or production SLOs.
