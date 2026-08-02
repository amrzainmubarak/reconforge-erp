# ADR 0226: Durable-job retry resumes committed checkpoints

## Status

Accepted for the bounded SQLite evidence slice.

## Context

P4-SCL-001 already proves concurrent claim/commit and cancellation, but retry
coupling remained untested. A transient worker failure after a committed
partition must release its lease, re-enter the retry state, and resume without
duplicating a business effect.

## Decision

Add `reconforge.benchmark.durable_job_retry` as a transport-free, synthetic
failure-injection harness. It uses the existing durable-job domain,
generation-fenced SQLite repository, and worker service. The injected fault is
bounded to one retry per job and may occur after the first checkpoint. The
closed manifest verifies retry count, completed jobs, exact partition-effect
count, zero duplicates, and drained queue/running depth.

## Boundaries

This does not add provider-specific exponential backoff or jitter, PostgreSQL
load parity, external side-effect compensation, or a 10K/100K/1M/10M capacity
claim. Those require separate runtime and hardware evidence.

## Rollback

Remove the harness, test, manifest entries, and execution evidence. No schema,
API, CLI, or persisted production behavior changes.
