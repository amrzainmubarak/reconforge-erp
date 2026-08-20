# ADR 0473: Preserve nullable organization scope in PostgreSQL job readers

- Status: accepted
- Date: 2026-08-09
- Decision owner: ReconForge execution owner

## Context

A live PostgreSQL durable-job backpressure profile completed its jobs but
reported no partition effects. The persisted jobs intentionally had no
organization, while replay readers used `str(nullable_value) or None`; SQL
NULL therefore became the literal organization scope `None`. PostgreSQL RLS
then hid the parent job from effect, transition, and lease-event reads.

## Decision

Use `_optional_scope_text` to preserve `None` as SQL NULL and stringify only
actual scope values. Apply it consistently to lease renewal, partition-effect,
transition, and lease-event reads. Workspace and entity scope remain explicit
and transaction-local.

## Verification

The focused null-scope regression passes. PostgreSQL 16.14 with a
non-superuser role passes the queue-cap backpressure profile and the 10K and
100K multi-worker effect profiles. The grouped worker, 500-partition, and
10K-partition gates also pass on the same service.

## Boundary

This is a replay-visibility repair and one-host synthetic concurrency evidence.
It does not establish distributed fairness, queue HA, host-failure recovery,
soak/SLOs, RPO/RTO, provider behavior, or production capacity.

## Reversibility

Revert the helper substitutions and regression test. No schema migration or
wire-format compatibility change is introduced.
