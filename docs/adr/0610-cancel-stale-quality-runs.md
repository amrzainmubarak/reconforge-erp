# ADR 0610: Cancel stale same-ref quality runs

## Status

Accepted — 2026-08-23

## Decision

CI, CodeQL, Security, and Docker workflows use a per-workflow/per-ref
concurrency group with `cancel-in-progress: true`. A newer commit supersedes an
older run for the same ref; its cancellation is not evidence of success or
failure of the superseded run.

## Boundary

This prevents redundant queued/running quality work and improves feedback
latency. It does not change test scope, security findings, release approval,
or production availability.

## Rollback

Any relaxation requires evidence that duplicate same-ref runs are intentionally
needed; removing stale-run cancellation without such evidence is not allowed.
