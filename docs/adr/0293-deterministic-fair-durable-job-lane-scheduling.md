# ADR 0293: Deterministic fair durable-job lane scheduling

- Date: 2026-08-03
- Status: accepted

## Decision

Add a small application-level scheduler that receives an explicit, unique tuple
of `(tenant_id, workspace_id, entity_id)` lanes and claims at most one job from
each lane per scheduling pass. A rotating process-local cursor starts the next
pass after the previously selected lane. Worker claims accept optional exact
workspace/entity filters; each repository applies them inside its existing
transaction, tenant boundary, row-locking, and lease-fencing rules.

## Rationale

The scheduler makes fairness behavior reproducible and testable without
weakening PostgreSQL row-level security or introducing a cross-tenant privileged
queue query. Exact lane filters prevent a busy workspace from consuming work
owned by a sibling workspace in the same tenant.

## Consequences and limits

The primitive proves deterministic round-robin selection for one scheduler loop
when configured lanes are non-empty. The cursor is deliberately not persisted
or shared across processes, so this is not a distributed fairness guarantee and
does not establish throughput, soak, HA/DR, SLO, or production-capacity claims.
An operator that needs multi-process fairness must provide an independently
verified scheduler-coordination mechanism before making that claim.

## Rollback

Remove `DurableJobLane`, `ScheduledDurableJob`,
`RoundRobinDurableJobScheduler`, the optional claim filters, their focused tests,
and this ADR/documentation entry. No migration or external system state is
changed.
