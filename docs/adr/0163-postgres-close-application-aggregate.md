# ADR 0163: Contract-compatible PostgreSQL close-management aggregate

## Status

Accepted — 2026-07-28

## Context

The historical PostgreSQL close repository is organization/fiscal-period scoped
and exposes a caller-owned API that differs from the eleven-operation Close
Application port. Adapting it by fabricating organization or fiscal-period
inputs would corrupt scope semantics and break local-first compatibility.

## Decision

Add migration 0030 with additive, explicitly named tenant/workspace close
period, task, and dependency tables under forced RLS. Preserve the legacy
tables and repository unchanged. The new adapter implements the exact
Application signatures, deterministic default tasks, bounded reads, exact
two-decimal readiness from integer counts, same-period acyclic dependencies,
blocked-task reasons, and atomic audit/outbox evidence.

Workspace-scoped period creation is serialized and rejects date overlap. Tasks
must satisfy dependencies before completion. A period may be Locked only when
every task is Complete or Not Applicable and exact readiness is 100.00. Locked
task/dependency state is immutable. Reopening requires an actor, timestamp, and
reason. This lock is ReconForge workflow metadata only; it does not lock a
source ERP or imply statutory close.

## Consequences

The additive design avoids a breaking migration and makes the two distinct
contracts explicit. PostgreSQL current-live behavior remains unclaimed until
the optional non-superuser overlap/DAG/readiness/lock/reopen/RLS lifecycle test
runs against a configured service.
