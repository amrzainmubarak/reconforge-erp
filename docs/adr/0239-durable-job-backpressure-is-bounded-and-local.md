# ADR 0239: Durable-job producer backpressure is bounded and local

- Status: accepted
- Date: 2026-08-02

## Decision

Add a separate `durable-job-load/backpressure-tier-v1` benchmark that submits
jobs from a producer thread while existing generation-fenced workers drain a
shared SQLite queue. The producer must not exceed a declared queued-job cap;
the result verifies zero duplicate effects and a fully drained queue.

## Evidence boundary

Two Windows 11/Python 3.14.6 local runs with 64 jobs, 8 workers, 4 tenants,
four partitions/job, and an eight-job cap observed a maximum queue depth of 8,
256 committed effects, zero duplicates, and identical structural/effect
digests. This is not distributed backpressure, PostgreSQL queue parity, soak,
or an SLO/capacity claim.

## Rollback

Remove the benchmark, tests, report, ADR, and package entries. No domain,
database schema, or production queue behavior changes.
