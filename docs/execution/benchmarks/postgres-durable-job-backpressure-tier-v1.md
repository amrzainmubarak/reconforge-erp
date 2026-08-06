# PostgreSQL durable-job backpressure profile

## Declaration

| Field | Value |
| --- | --- |
| Profile | `postgres-durable-job-load/backpressure-tier-v1` |
| Database | PostgreSQL 16 disposable service |
| Workers | 8 independent worker connections |
| Tenant lanes | 4 |
| Jobs | 64 (16 per lane) |
| Partitions/job | 4 |
| Queue cap | 4 queued/retrying jobs per `(tenant, workspace, entity)` lane |
| Declared effects | 256 |

## Acceptance invariants

- Producers submit all 64 jobs using the atomic bounded-submit contract.
- At least one submission is rejected while a lane is at its cap, and the
  producer retries without creating a row or transition for the rejected
  attempt.
- Observed queued/retrying depth never exceeds four per lane.
- Every declared job reaches `completed` with four ordered effects.
- No duplicate `(job, partition)` effect is observed.
- Forced-RLS tenant/workspace/entity scope remains isolated.
- Queued/retrying and running depths are both zero after the drain.
- Per-lane completion counts are exactly 16 each and integrity digests exist.

## Observed local run

The local PostgreSQL 16 disposable-service run completed 64/64 jobs and
256/256 effects in 1.3913 seconds. It observed a maximum queue depth of four,
12 rejected bounded-submit attempts, zero duplicate effects, and zero final
queued/running residue. The run used Windows 11, Python 3.14.6, and one
database host. The effect-set digest was
`b86c16598f6acdf95dd23a00826bf8be373d1608de2cbaafc08ff19cb4ba19d5`; the
structural manifest digest was
`ab6bebb3bb1f2ffad458865487acaef32f1a67da78da0bc7b53292b57caea001`.

## Interpretation

This is a bounded synthetic queue-cap and drain correctness gate using one
PostgreSQL host and independent producer/worker connections. The observed
queue depth and retry count are workload observations, not throughput,
capacity, SLO, or sizing claims. Queue HA, automatic failover, host loss,
cross-host fairness, soak, RPO/RTO, and production deployment remain
unverified.

## Current rerun

On 2026-08-06 the profile passed against the local PostgreSQL 17.10 service
using the non-privileged `reconforge_app` role: 64/64 jobs and 256/256 effects
completed, the queue cap stayed at four, 24 bounded submissions were rejected
and retried, zero duplicate effects remained, and all four lanes completed
16 jobs. Runtime was 1.5469s on Python 3.12.13/Windows 11. Effect digest is
`0e21f3ddd95c8704c00c16262aaff5dab9b443e22c9ccfd0a8fb17265abcf06c` and the
machine-readable current report is
`postgres-durable-job-backpressure-current-2026-08-06.json` with report digest
`60de637cf3633c14ae14ac763e9325c61cca97f82a27470cea096cb9f248d2c9`.
The interpretation boundary above is unchanged.
