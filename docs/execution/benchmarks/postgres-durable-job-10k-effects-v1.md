# PostgreSQL durable-job 10K-effect profile

## Declaration

| Field | Value |
| --- | --- |
| Profile | `postgres-durable-job-load/10k-effects-v1` |
| Database | PostgreSQL 16 service |
| Workers | 16 independent worker connections |
| Tenant lanes | 4 |
| Jobs | 2,500 (625 per lane) |
| Partitions/job | 4 |
| Declared effects | 10,000 |

## Acceptance invariants

- Every declared job reaches `completed`.
- Every job has exactly four ordered partition effects.
- No duplicate `(job, partition)` effect is observed.
- Forced-RLS tenant/workspace/entity scope remains isolated.
- Queued/retrying and running depths are both zero after the drain.
- Per-tenant completion counts are exactly 625 each.
- Effect-set and structural manifest digests are present.

## Observed local run

The published artifact records a Windows 11/Python 3.14.6 run on one local
PostgreSQL 16 container: 10,000 effects completed in 30.4805 seconds at
82.0197 jobs/second. These timings are observations, not capacity or SLO
claims. Its effect-set digest is
`62b8f8ea4b19b9644b4fd356db3fc6d96d5922ebfcfe1a4a5aa4aba035e83c2f` and its
structural manifest digest is
`995184fd3d9bbbb1a8d8f54f619af700673a71e031a35b9c0f609a5cc741b512`.

## Interpretation

This is a bounded synthetic, single-host PostgreSQL correctness/concurrency
gate with independent worker connections. It does not prove throughput,
soak, backpressure coupling, queue HA, automatic failover, host loss,
cross-host fairness, RPO/RTO, or production sizing. Larger tiers remain open.
