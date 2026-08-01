# ADR 0103: Persist a versioned, fail-closed durable-job state machine

- Status: Accepted
- Date: 2026-07-27
- Scope: P1-PLAT-003 and checkpoint foundation for P1-PLAT-004

## Context

The local database had an operational history table and PostgreSQL
reconciliation had a specialized execution lifecycle, but there was no shared
job aggregate implementing all required queued, running, paused, retrying,
failed, completed, and cancelled states. Progress, idempotency, output identity,
retry ceilings, and transition evidence therefore had no backend-neutral
contract.

## Decision

Introduce schema-v1 `DurableJob` as a pure immutable domain aggregate. Progress
uses bounded integer units, never binary floating point. Inputs, configuration,
checkpoints, and outputs are SHA-256-addressed. Completion requires full
progress, a canonical UTC completion time, and an output manifest. Failure
stores only an allowlisted safe error code. Retry count cannot exceed its fixed
ceiling. Invalid, self-invented, terminal, or time-reversing transitions fail.

SQLite migration 21 stores the aggregate and an append-only transition table.
Submission owns `BEGIN IMMEDIATE`, atomically binds tenant/scope/idempotency key,
and replays only an identical submission. State changes use compare-and-swap on
the prior version and append transition evidence in the same transaction.
Checkpoint progress is monotonic and must precede full completion. Backup,
restore, and public database export include both job tables.

`DurableJobApplicationService` depends only on a repository port. Tenant-scoped
not-found behavior does not reveal whether another tenant owns the supplied ID.

## Consequences

- Local Community jobs have a durable, resumable persistence primitive.
- An injected transition-evidence failure rolls back the state update.
- Stale workers cannot commit over a newer job version.
- Transition UPDATE/DELETE operations are blocked by SQLite triggers.
- A version-20 database upgrades additively through migration 21. Downgrade
  requires restoring a pre-migration backup; schema 20 cannot represent jobs
  created after migration and no lossy automatic downgrade is offered.
- A generic worker lease, crash takeover, PostgreSQL parity, scheduling,
  authorization integration, and process/host-loss proof remain open. Therefore
  P1-PLAT-003 stays in progress and P1-PLAT-004 is not claimed complete.

## Claim boundary

This is tested local SQLite durability and application/domain behavior. It is
not a distributed queue, exactly-once transport claim, HA/DR proof, supported
throughput claim, or enterprise-readiness evidence.
