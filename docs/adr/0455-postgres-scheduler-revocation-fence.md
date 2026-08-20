# ADR 0455: Re-evaluate scheduler policy before dispatch

- Status: accepted
- Date: 2026-08-09
- Scope: PostgreSQL scheduled-work dispatch authorization

## Decision

The PostgreSQL scheduler keeps its existing lane-level, pre-connection
service-account policy check and adds a second check immediately before
`SchedulerApplicationService.process_due`. If policy is revoked during the
connection/setup window, the worker fails closed before any schedule claim or
dispatch mutation and still closes the fresh connection.

The check is opt-in through the existing worker settings; unconfigured
Community/local-compatible operation remains unchanged. This guard is
authorization fencing, not a lease or broker guarantee.

## Non-goals and rollback

This does not provide distributed invalidation latency bounds, queue HA,
exactly-once broker delivery, or production scheduling SLOs. Rollback is a
code-only revert of the second check and regression test; no migration or
persisted-data change is required.

## Evidence boundary

The focused scheduler worker contract injects a permission revocation between
the pre-connection and dispatch checks and proves no schedule processing is
invoked while the connection is cleaned up. The test uses a fake connection and
does not establish live PostgreSQL or cross-process behavior.
