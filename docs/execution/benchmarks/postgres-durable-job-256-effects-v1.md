# PostgreSQL durable-job 256-effect profile

## Declaration

| Field | Value |
| --- | --- |
| Profile | `postgres-durable-job-load/256-effects-v1` |
| Database | PostgreSQL 16 Alpine CI service |
| Workers | 8 independent worker connections |
| Tenant lanes | 4 |
| Jobs | 64 (16 per lane) |
| Partitions/job | 4 |
| Declared effects | 256 |

## Acceptance invariants

- Every declared job reaches `completed`.
- Every job has exactly four ordered partition effects.
- No duplicate `(job, partition)` effect is observed.
- The tenant/workspace/entity lane remains scoped under forced RLS.
- A second worker cannot take over an active lease; the claim path rechecks
  lease ownership after locking the job row.
- Queued/retrying and running depths are both zero after the drain.
- The effect-set and structural manifest digests are present.

## Interpretation

The profile uses synthetic records and one PostgreSQL service host. It is a
multi-connection contention and correctness gate, not a throughput,
capacity, soak, SLO, HA/DR, RPO/RTO, or production-readiness claim. Larger
tiers and independent failure domains remain open work.
