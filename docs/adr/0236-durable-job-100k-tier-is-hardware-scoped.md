# ADR 0236: Publish a bounded 100K durable-job tier

- Date: 2026-08-02
- Status: accepted

## Decision

Publish `durable-job-load/100k-tier-v1` as a declared SQLite benchmark only:
10,000 jobs, 10 partition effects per job, 16 workers, and four statically
tenant-pinned lanes (100,000 committed effects). The benchmark uses a bounded
600-second lease and a 300-second SQLite busy timeout. These values are
benchmark parameters, not Community or production defaults.

## Evidence boundary

Two complete Windows 11/Python 3.14.6 runs verified queue drain, 100,000
committed effects, zero duplicate effects, fair tenant completion, and stable
effect/manifest digests. This is one-host, one-database SQLite evidence. It
does not prove PostgreSQL parity, distributed throughput, backpressure,
soak/SLOs, HA/DR, or 1M/10M capacity.

## Rollback

Remove the 100K profile, report, tests, ADR, and optional busy-timeout plumbing;
no schema or external state is changed.
