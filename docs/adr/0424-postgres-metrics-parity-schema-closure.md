# ADR 0424: Close the PostgreSQL metrics parity fixture dependency graph

- **Status**: accepted
- **Date**: 2026-08-07
- **Scope**: `tests/test_application_metrics.py` PostgreSQL parity gate

## Context

The metrics repository intentionally reads close, exception, evidence,
control, reconciliation, and matching data. The live parity test installed
only the domain and metrics schemas, so a disposable PostgreSQL run could fail
with a generic metrics-operation error when one of those dependency tables was
absent. That was a test-environment defect, not evidence that the adapter
should silently fabricate empty metrics.

## Decision

Install the exact dependency schema helpers used by the metrics queries before
the metrics schema in the live test: close application, exception queue,
evidence application, control testing, reconciliation, and matching. Keep the
existing least-privilege grants and SQLite comparison unchanged. Do not add
placeholder tables or fallback zero values to the production adapter.

## Verification and boundary

The focused parity test remains capability-gated when no PostgreSQL DSN exists;
the hosted server-boundary job is the runtime proof. Local static and full
regression gates must pass. This does not prove provider integration,
statutory metrics, throughput, HA/DR, or production readiness.
