# Durable-job 10K tier v1

Date: 2026-08-02 (Africa/Cairo)

Profile: `durable-job-load/10k-tier-v1`

| Declared input | Value |
| --- | ---: |
| Workers | 16 |
| Jobs | 1,000 |
| Partitions per job | 10 |
| Tenant lanes | 4 |
| Committed partition effects | 10,000 |

Environment: Windows 11 (`10.0.26200`), Python 3.14.6, AMD64, 16 logical
CPUs, one shared SQLite database in WAL mode. The run uses the existing
generation-fenced durable-job worker and checkpoint repository; no new
persistence primitive is introduced.

Two complete runs produced:

| Run | Runtime (s) | Throughput (jobs/s) | Effect-set digest | Manifest digest |
| ---: | ---: | ---: | --- | --- |
| 1 | 15.6270 | 63.9917 | `0e750959e9661f6f2c463dde311c87928bf53ad56facfdd9274b1feeca674dc3` | `ef430b4033a81f93e3e5a38bd9c9773a346b48b29fe2d568a7c63049a23675ff` |
| 2 | 11.6864 | 85.5692 | `0e750959e9661f6f2c463dde311c87928bf53ad56facfdd9274b1feeca674dc3` | `ef430b4033a81f93e3e5a38bd9c9773a346b48b29fe2d568a7c63049a23675ff` |

Observed invariants: 1,000/1,000 jobs completed, 10,000/10,000 effects
committed, zero duplicate `(job_id, partition_key)` effects, and zero queued
or running jobs at audit. Runtime, memory, and throughput are observations,
not sizing or SLO commitments.

Limitations: one host and one SQLite writer domain; workers are statically
tenant-pinned; PostgreSQL parity, queue backpressure, retry/backoff coupling,
soak, cancellation-under-load, HA/DR, and 100K/1M/10M tiers remain
unverified.
