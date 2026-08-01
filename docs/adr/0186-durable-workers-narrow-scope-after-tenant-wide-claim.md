# ADR 0186: Durable workers narrow scope after tenant-wide claim

Status: Accepted

## Context

A scheduler must discover runnable work across one tenant, but retaining that broad scope while updating a selected job allows accidental sibling-workspace or sibling-entity effects.

## Decision

Claim remains an explicit tenant-wide scheduling operation. Immediately after the selected row is locked and decoded, the same transaction narrows to that job's immutable workspace and entity before transition, lease, lease-event, checkpoint, partition-effect, or release writes. Every later resume, heartbeat, transition, and evidence read re-derives the scope from the durable parent and re-queries under it.

Migration 0042 makes `durable_jobs` directly workspace/entity aware and makes all four child-evidence tables visible only when their parent job is visible under the active scope.

## Consequences

- Tenant-wide discovery is separated from job-scoped execution.
- Crash/resume and fencing semantics remain unchanged.
- API principals still require an independent authorized-scope composition slice; knowing a job ID is not treated as authority.
