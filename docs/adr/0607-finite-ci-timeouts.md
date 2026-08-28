# ADR 0607: Bound long-running CI jobs

## Status

Accepted — 2026-08-23

## Decision

The Python test matrix has a 45-minute job timeout and the PostgreSQL HA/DR
drill has a 30-minute job timeout. Workflow contract tests enforce both
values. A timeout is a failure signal requiring triage, not a pass or a reason
to weaken the underlying test.

## Boundary

This prevents indefinitely consuming hosted runners and makes stalled jobs
observable. It does not prove test completion, HA/DR, capacity, or recovery
objectives.

## Rollback

Changing a bound requires measured runtime evidence and an updated workflow
contract; removing the bound is not an acceptable rollback.
