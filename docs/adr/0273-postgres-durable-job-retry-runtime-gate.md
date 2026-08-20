# ADR 0273 — PostgreSQL durable-job retry and recovery runtime gate

- **Status:** Accepted
- **Date:** 2026-08-03
- **Scope:** Synthetic PostgreSQL durable-job worker contract

## Decision

Extend the live PostgreSQL durable-job contract with one injected transient
failure after a committed partition. The worker must transition to `retrying`,
release its lease, allow a recovery worker to claim the job, skip the committed
partition, finish the remaining partition exactly once, and retain the ordered
transition reasons and retry count.

## Rationale

Existing PostgreSQL evidence covered concurrent claims, leases, takeovers, and
crash-style resume. This adds the normal transient-failure path that production
workers use for retryable faults, while exercising the real repository and
database transaction boundary rather than a mock queue.

## Limits

The contract is a small synthetic two-partition runtime proof. It does not
establish PostgreSQL capacity, soak/SLOs, distributed queue behavior,
automatic process supervision, HA/DR, or production retry tuning.

