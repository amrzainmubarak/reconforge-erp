# ADR 0584: Current PostgreSQL durable-job soak and backpressure evidence

## Status

Accepted — 2026-08-23

## Decision

Promote the current local PostgreSQL backpressure and repeated-small-soak run
to dated evidence, retaining the exact workload observations and digests in a
schema-closed benchmark artifact and the benchmark evidence index.

## Evidence boundary

The run uses synthetic tenant lanes and the non-privileged `reconforge_app`
role on one local PostgreSQL service. It proves bounded queue-cap behavior,
effect uniqueness, queue drain, repeated effect-digest stability, and the
declared workload shape. It does not prove capacity, throughput SLOs, queue HA,
cross-host fairness, automatic failover, host loss, RPO/RTO, or production
operation.

## Reversal

Remove the dated artifact/index entry and its execution record. No runtime or
schema migration is required to roll back this evidence publication.
