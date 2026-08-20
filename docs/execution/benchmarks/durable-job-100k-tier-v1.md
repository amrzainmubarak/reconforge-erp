# Durable-job 100K tier v1

Date: 2026-08-02 (Africa/Cairo)

Profile: `durable-job-load/100k-tier-v1`

| Declared input | Value |
| --- | ---: |
| Workers | 16 |
| Jobs | 10,000 |
| Partitions per job | 10 |
| Tenant lanes | 4 |
| Committed partition effects | 100,000 |
| Lease seconds | 600 |
| SQLite busy timeout seconds | 300 |

Environment: Windows 11 (`10.0.26200`), Python 3.14.6, AMD64, 16 logical
CPUs, one shared SQLite database in WAL mode. Workers use the existing
generation-fenced durable-job worker and checkpoint repository.

Two complete runs produced:

| Run | Runtime (s) | Throughput (jobs/s) | Peak traced memory (MiB) | Effect-set digest | Manifest digest |
| ---: | ---: | ---: | ---: | --- | --- |
| 1 | 208.5061 | 47.9602 | 0.1582 | `f648511d960f00df0afd3f2545f6f1ae58a4a9056846a9a6a0f17754f00031f4` | `298ccbbb6c10031fdbf84402b7f22c8d4bb566e4faefd8adb86c204081b9e423` |
| 2 | 218.8465 | 45.6941 | 0.1445 | `f648511d960f00df0afd3f2545f6f1ae58a4a9056846a9a6a0f17754f00031f4` | `298ccbbb6c10031fdbf84402b7f22c8d4bb566e4faefd8adb86c204081b9e423` |

Observed invariants: 10,000/10,000 jobs completed, 100,000/100,000 effects
committed, zero duplicate `(job_id, partition_key)` effects, zero queued or
running jobs at audit, and 2,500 completions per tenant. Runtime, memory, and
throughput are observations, not sizing or SLO commitments.

Contention boundary: 32 workers failed with SQLite lock errors; 16 workers
with the default 60-second busy timeout also failed under this workload. The
published profile therefore keeps 16 workers and uses the explicitly bounded
300-second benchmark timeout. This does not make SQLite a parallel writer.

Limitations: one host and one SQLite writer domain; PostgreSQL parity,
backpressure, retry/backoff coupling, soak, cancellation-under-load, HA/DR,
and 1M/10M tiers remain unverified. No production default or global capacity
claim follows from this report.
