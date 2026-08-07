# ADR 0429: Safe telemetry for reconciliation scheduler cycles

- **Date**: 2026-08-07
- **Status**: accepted

## Context

The reconciliation scheduler returned aggregate outcomes but did not expose a
safe trace/metric boundary for each worker cycle. Operators need lifecycle
visibility without exporting tenant identifiers, record values, credentials, or
other financial data.

## Decision

Accept an optional `ObservabilityRuntime` on
`PostgresReconciliationScheduler`. Each bounded worker cycle creates the
`reconforge.reconciliation.worker` span and records a job transition with the
closed low-cardinality attributes `job.type`, `job.status`,
`reconforge.operation`, and `reconforge.result`. Telemetry is disabled by
default and errors are recorded before the original worker failure is surfaced.
Worker IDs, tenants, record identifiers, amounts, and connection details are
never attributes.

## Verification and boundary

The scheduler contract injects a synthetic telemetry sink and proves one span
and one completion transition per worker cycle with no tenant disclosure; the
full local regression, Ruff, Mypy, package build, and diff-check pass. This is
instrumentation evidence only, not external collector delivery, alerting,
throughput, capacity, HA/DR, or production SLO evidence.
