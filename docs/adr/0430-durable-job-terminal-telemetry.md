# ADR 0430: Safe telemetry for durable-job terminal transitions

- **Date**: 2026-08-07
- **Status**: accepted

## Context

Durable-job claim telemetry existed, but terminal worker outcomes were not
visible through the same operational boundary. Per-partition spans would be
too expensive at scale and could encourage high-cardinality identifiers.

## Decision

Emit optional, disabled-by-default `ObservabilityRuntime` spans and job
transitions for terminal worker operations: complete, complete-partition,
retry, fail, pause, and cancel. Attributes are limited to the existing closed
contract (`job.type`, `job.status`, `reconforge.operation`, and
`reconforge.result`). Persistence failures record an error transition before
the original exception is re-raised. Heartbeats, checkpoints, and individual
partition effects remain uninstrumented to avoid per-record telemetry volume.

## Verification and boundary

The observability contract proves successful completion and an injected
terminal persistence failure, while retaining the existing secret-exclusion
assertions. This is lifecycle instrumentation evidence only; it does not
claim collector delivery, alerting, throughput, capacity, HA/DR, or production
SLOs.
