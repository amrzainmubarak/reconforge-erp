# ADR 0469: Expose sanitized durable-job queue health in the local CLI

- Status: accepted
- Date: 2026-08-09
- Decision owner: ReconForge execution owner

## Context

The E-628 queue snapshot was available to application callers, but local
operators had no supported command to inspect queue depth and lease health.
The existing generic job-history command is a different legacy table and does
not represent durable-job execution state.

## Decision

Add `reconforge ops durable-job-queue --tenant ...` for SQLite Community mode.
It uses the same application/repository projection as code callers, supports
optional workspace/organization/entity lane filters, and prints only the
sanitized snapshot fields plus derived queue/total counts. Job IDs,
idempotency keys, digests, and financial payloads are never printed.

## Boundaries

This is a local read-only operator surface. It does not add network access,
PostgreSQL API exposure, distributed authorization, queue HA, or production
operations evidence.

## Verification

The CLI contract creates one synthetic durable job, invokes the command, and
asserts queue health is visible while the job identifier is absent.
