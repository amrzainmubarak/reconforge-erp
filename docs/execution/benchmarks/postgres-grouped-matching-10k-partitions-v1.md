# PostgreSQL grouped-matching 10K-partition profile

## Declaration

| Field | Value |
| --- | --- |
| Profile | `postgres-grouped-matching/10k-partitions-v1` |
| Database | PostgreSQL 16 disposable service |
| Workers | 16 independent worker tasks using a bounded 16-connection pool |
| Runs | 1,000 |
| Partitions/run | 10 |
| Declared partitions | 10,000 |
| Modes | one-to-many, many-to-one, many-to-many, portfolio, fx-many-to-one |
| Expected result rows | 24,000 |

## Acceptance invariants

- Every run reaches `Complete` and every declared partition has one checkpoint.
- Every mode completes exactly 200 runs.
- Result-row cardinality is exactly 24,000 with zero duplicate result
  identities.
- Failed and active run counts are zero after the drain.
- The effect-set and structural manifest digests are present.
- A bounded PostgreSQL connection pool reuses connections and closes all idle
  resources after the run; tenant-local transaction scope remains applied by
  the existing boundary.

## Observed local run

The local PostgreSQL 16 disposable-service run completed 1,000/1,000 runs and
10,000/10,000 partitions with 24,000/24,000 expected result rows, zero
duplicate identities, zero failed/active runs, and 200 completions per mode.
Observed wall time was approximately 303.5 seconds on Windows 11/Python 3.14.6
with one database host. The effect-set digest was
`14e33ba117d7be05da5290346736ea6a594c1a0a52689b4939b665c0c674c88b`; the
structural manifest digest was
`3d69594eeaf117934005ea150a39bdc3e9d4ce3d6c9afdd5e214f0839abaf997`.

## Interpretation

This is a bounded synthetic PostgreSQL correctness/concurrency gate for the
declared grouped-matching modes. The pool addresses local connection churn;
the observed runtime is not a throughput, capacity, SLO, soak, or production
sizing claim. Cross-host scheduling, queue HA, automatic failover, host loss,
large-domain diversity beyond the declared fixtures, provider I/O, statutory
posting, write-back, and HA/DR remain unverified.
