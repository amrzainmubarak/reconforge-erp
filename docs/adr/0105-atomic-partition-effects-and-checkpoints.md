# ADR 0105: Commit partition effects and checkpoints as one business unit

- Status: Accepted
- Date: 2026-07-27
- Scope: P1-PLAT-004

## Context

A durable checkpoint alone can still duplicate business output. If an effect is
published and the checkpoint fails, a restarted worker repeats the effect. If
the checkpoint commits first, a crash can skip an effect that never existed.
Lease fencing prevents stale writers but does not solve this atomicity gap.

## Decision

Migration 23 adds immutable `durable_job_partition_effects`. Each effect binds
the job, deterministic partition key and ordinal, cumulative integer progress,
input/output digests, output reference, commit time, and exact job version.

The worker Application service has two safe operations:

- `commit_partition` writes a non-final effect plus its checkpoint transition;
- `complete_partition` writes the final effect, completed state, output
  manifest, transition evidence, lease deletion, and release event.

The SQLite repository verifies the unexpired fencing generation and next
contiguous ordinal, then commits all rows in one `BEGIN IMMEDIATE` transaction.
Effect rows are unique by partition key, ordinal, and job version and are
database-immutable. A resumed worker lists committed effects and skips their
partition keys.

## Consequences

An injected transition failure rolls back the effect and checkpoint together.
A two-partition workload produces identical effect semantics and output-manifest
identity in uninterrupted and connection-close/restart execution. The resumed
path preserves partition one, takes over at expiry, skips it, and commits only
partition two; both paths contain exactly two effects.

This closes P1-PLAT-004 for the defined local safe-partition-workload exit. It
does not make arbitrary external systems transactional. Connectors, object
stores, email, ERP write-back, or other resources require their own idempotency,
outbox, compensation, and crash tests. It is not an exactly-once transport,
host-loss, HA/DR, or PostgreSQL-parity claim.

## Rollback

Restore a pre-migration-23 backup. Dropping effect history would remove the
proof used to skip completed partitions and is not a safe in-place downgrade.
