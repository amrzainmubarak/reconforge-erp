# Durable-job bounded backpressure tier v1

Date: 2026-08-02 (Africa/Cairo)

Profile: `durable-job-load/backpressure-tier-v1`

| Declared input | Value |
| --- | ---: |
| Workers | 8 |
| Jobs | 64 |
| Partitions per job | 4 |
| Tenant lanes | 4 |
| Maximum queued jobs | 8 |
| Declared effects | 256 |

Two complete local runs on Windows 11/Python 3.14.6 produced:

| Run | Runtime (s) | Observed max queue | Completed jobs | Effects | Effect digest | Manifest digest |
| ---: | ---: | ---: | ---: | ---: | --- | --- |
| 1 | 1.3484 | 8 | 64 | 256 | `08fc4c6c8f366be08ad21ff9b800886574bd0194010aa760377c2621d33718a5` | `dce9cbddac76b1026fae417dc957a555d6edb2ba51f007ba7a6d2a3494dbc495` |
| 2 | 1.6830 | 8 | 64 | 256 | `08fc4c6c8f366be08ad21ff9b800886574bd0194010aa760377c2621d33718a5` | `dce9cbddac76b1026fae417dc957a555d6edb2ba51f007ba7a6d2a3494dbc495` |

Both runs ended with zero queued/running jobs and zero duplicate
`(job_id, partition_key)` effects. The cap is enforced by the producer while
workers claim and commit through the existing durable-job repository.

Limitations: one shared SQLite writer domain; this proves only a local queue
cap. PostgreSQL queue parity, distributed backpressure, retry backoff, soak,
cancellation-under-load, HA/DR, and production SLO/capacity remain
unverified.
