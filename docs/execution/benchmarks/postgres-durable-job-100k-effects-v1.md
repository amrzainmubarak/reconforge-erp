# PostgreSQL durable-job 100K-effect profile

## Declaration

| Field | Value |
| --- | --- |
| Profile | `postgres-durable-job-load/100k-effects-v1` |
| Database | PostgreSQL 16 service |
| Workers | 16 independent worker connections |
| Tenant lanes | 4 |
| Jobs | 2,500 (625 per lane) |
| Partitions/job | 40 |
| Declared effects | 100,000 |

## Acceptance invariants

- Every declared job reaches `completed`.
- Every job has exactly forty ordered partition effects.
- No duplicate `(job, partition)` effect is observed.
- Forced-RLS tenant/workspace/entity scope remains isolated.
- Queued/retrying and running depths are both zero after the drain.
- Per-tenant completion counts are exactly 625 each.
- Effect-set and structural manifest digests are present.

## Observed local run

The published artifact records a Windows 11/Python 3.14.6 run on one local
PostgreSQL 16 container: 100,000 effects completed in 202.1521 seconds at
12.3669 jobs/second. These timings are observations, not capacity or SLO
claims. Its effect-set digest is
`e79d9c21a6243a9d4c9bdd3c09471551fcb7ae9aaf6f26241ef94d9319529252` and its
structural manifest digest is
`d56fd2fe2bdcda9161c9545e456347c136adf15e15b74c543904147c3d06f890`.

## Interpretation

This is a bounded synthetic, single-host PostgreSQL correctness/concurrency
gate with independent worker connections. It does not prove throughput,
soak, backpressure coupling, queue HA, automatic failover, host loss,
cross-host fairness, RPO/RTO, or production sizing. Larger tiers remain open.
