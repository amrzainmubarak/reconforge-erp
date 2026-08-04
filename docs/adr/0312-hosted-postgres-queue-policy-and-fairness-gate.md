# ADR 0312: Keep hosted PostgreSQL queue-policy and lane-fairness evidence explicit

- Status: accepted
- Date: 2026-08-04
- Scope: bounded durable-job backpressure and scheduler runtime evidence

## Context

The PostgreSQL durable-job implementation already has additive atomic queue
caps, retry/cancellation behavior, tenant/workspace/entity lane filters, and a
process-scoped round-robin scheduler. Those contracts had local and historical
hosted evidence, but the current `server-boundaries` command selected only the
10K load profile and did not explicitly retain the queue-policy/fairness paths.

## Decision

Add a separate hosted invocation of the existing live tests
`test_live_postgres_job_application_contract_and_rls` and
`test_live_postgres_round_robin_scheduler_is_lane_scoped_and_deterministic`.
The command reuses the real non-privileged PostgreSQL role and existing RLS,
backpressure, retry/cancellation, and scheduler implementations; it adds no
new queue primitive or production setting.

## Evidence boundary

The gate proves bounded synthetic queue-cap rejection/replay, lease/retry
cleanup, tenant isolation, and deterministic fairness for one scheduler loop
on one PostgreSQL service. It does not prove throughput, global/distributed
fairness, soak, queue HA, automatic failover, capacity, or production SLOs.

## Rollback

Remove the additional workflow invocation, this ADR, its manifest entry, and
the execution evidence. Existing local and 10K hosted profiles remain.
