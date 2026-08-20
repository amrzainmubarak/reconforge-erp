# PostgreSQL durable-job 1M-effect profile

## Declaration

| Field | Value |
| --- | --- |
| Profile | `postgres-durable-job-load/1m-effects-v1` |
| Database | PostgreSQL 16 service |
| Workers | 16 independent worker connections |
| Tenant lanes | 4 |
| Jobs | 2,500 (625 per lane) |
| Partitions/job | 400 |
| Declared effects | 1,000,000 |

## Acceptance invariants

- Every declared job reaches `completed`.
- Every job has exactly four hundred ordered partition effects.
- No duplicate `(job, partition)` effect is observed.
- Forced-RLS tenant/workspace/entity scope remains isolated.
- Queued/retrying and running depths are both zero after the drain.
- Per-tenant completion counts are exactly 625 each.
- Effect-set and structural manifest digests are present.

## Observed local run

The published artifact records a Windows 11/Python 3.12.13 run on one local
PostgreSQL 16 container: 1,000,000 effects completed in 1,932.3678 seconds at
1.2937 jobs/second. These timings are observations, not capacity or SLO
claims. Its effect-set digest is
`95ba466b31a08f5b3a4506d0b8fc5b44742f01627c79aea772e46d7bd073ee5c` and its
structural manifest digest is
`252eb01a1b679deb977141d9e1d931e89469d161877e8fdd1a4e88c6ae642103`.

## Interpretation

This is a bounded synthetic, single-host PostgreSQL correctness/concurrency gate
with independent worker connections. It does not prove throughput, soak,
backpressure coupling, queue HA, automatic failover, host loss, cross-host
fairness, RPO/RTO, or production sizing. Larger tiers remain open.
