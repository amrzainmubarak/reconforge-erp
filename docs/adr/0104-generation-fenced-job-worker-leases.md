# ADR 0104: Fence durable-job workers with expiring lease generations

- Status: Accepted
- Date: 2026-07-27
- Scope: P1-PLAT-003 closure and P1-PLAT-004 recovery foundation
- Supersedes: The open generic-worker limitation recorded by ADR 0103

## Context

Atomic job state and checkpoints do not prevent a worker that paused, lost its
process, or lost connectivity from writing after another worker resumes the
same job. A status flag alone is not a fencing token. Recovery also needs a
deterministic rule for when takeover is permitted and which checkpoint survives.

## Decision

SQLite migration 22 adds one current lease per job plus immutable lease events.
A lease carries tenant, owner, monotonically increasing generation, acquisition,
renewal, and expiry times. Claiming owns one `BEGIN IMMEDIATE` transaction and:

1. prioritizes expired running jobs, then retrying jobs, then queued jobs;
2. advances the job state/version or records a running-state takeover;
3. allocates the next generation from immutable history;
4. writes the current lease, job transition, and lease event atomically.

Heartbeat succeeds only for the exact active owner/generation, before expiry,
and only when expiry is extended. Checkpoint and terminal writes require the
same unexpired fencing token. Completion, pause, retry, failure, and worker
cancellation release the lease and append release evidence in the same
transaction. Non-worker state changes cannot enter or mutate worker-owned
states through the ordinary repository method.

After expiry, takeover increments both job version and lease generation while
retaining the last committed completed-unit count and checkpoint digest. The
old worker is rejected even if it computed output before takeover.

## Consequences

- All seven P1-PLAT-003 states now have tested local application/persistence
  paths, atomic idempotency, transition evidence, retry ceilings, and output
  manifest gates. P1-PLAT-003 is complete for its defined local foundation exit.
- P1-PLAT-004 is in progress: a real connection close/reopen test proves expiry
  takeover resumes the last committed checkpoint and stale writes are fenced.
- Actual workload side effects, crash injection between external effects,
  PostgreSQL parity, and host/filesystem-loss tests remain open. No exactly-once
  transport or distributed-lock claim is made.

## Rollback

Restore a pre-migration-22 backup. Dropping lease tables in place would remove
fencing history and is not a safe rollback. Jobs created or advanced under the
lease contract must not be silently downgraded.
