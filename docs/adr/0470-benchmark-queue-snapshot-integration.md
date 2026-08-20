# ADR 0470: Reuse queue snapshots in durable-job benchmark drain checks

- Status: accepted
- Date: 2026-08-09
- Decision owner: ReconForge execution owner

## Context

The durable-job load profiles independently queried status counts with raw SQL
after a run. That duplicated queue semantics and could let benchmark evidence
drift from the operational projection used by callers and the local CLI.

## Decision

Use `DurableJobQueueSnapshot` from the SQLite and PostgreSQL repositories for
final queue/running drain checks in the load profiles. Aggregate one explicit
tenant snapshot per declared lane; retain raw SQL only for immutable effect
duplicate/effect-digest inspection where the snapshot intentionally has no
payload or identity data.

## Boundary

This improves evidence-path consistency only. It does not add a throughput,
capacity, distributed fairness, queue HA, or production-sizing claim.
