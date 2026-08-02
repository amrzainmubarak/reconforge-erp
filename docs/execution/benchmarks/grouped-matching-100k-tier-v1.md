# Grouped matching 100K tier v1

Date: 2026-08-02 (Africa/Cairo)

## Workload

The profile contains 100,000 exact-USD records arranged as 25,000 independent
true many-to-many partitions. Each partition has two left records (30 and 70)
and two right records (25 and 75). Every partition is evaluated through
`GroupedSubsetSumStrategy` and `GroupedMatchingApplicationService`; every
1,000th partition is replayed with reversed input order.

Profile ID: `grouped-matching/100k-record-true-many-to-many-v1`

## Observed result

| Measurement | Run 1 | Run 2 |
| --- | ---: | ---: |
| Partitions | 25,000 | 25,000 |
| Records | 100,000 | 100,000 |
| Matched partitions | 25,000 | 25,000 |
| Ambiguous / unmatched | 0 / 0 | 0 / 0 |
| Strategy evaluations | 25,000 | 25,000 |
| Cross-engine mismatches | 0 | 0 |
| Permutation mismatches | 0 | 0 |
| Runtime (seconds) | 42.0286 | 40.7803 |
| Peak traced memory (MiB) | 7.7915 | 7.7700 |

Environment: Windows 11 `10.0.26200`, Python `3.14.6`, AMD64, 16 logical CPUs.

Effect digest (both runs):
`dda82223212af64038094cc21d4a6fed08af76d86a5b9920c1f4bd187d33be41`.

Manifest digest (both runs):
`60aad17ab30533964f61e1b5c64aeba58e56915ee62ac5a75325c25a7133981a`.

## Interpretation boundary

This is reproducible synthetic algorithm evidence for a partitioned,
single-process workload. It is not a distributed capacity result, SLO, or
production readiness claim. FX, fees, partial settlement, dense ambiguity,
provider I/O, PostgreSQL runtime parity, soak/failure load, and the 1M tier are
not covered. The workload does not prove unbounded many-to-many search; the
published per-partition record and search-evaluation ceilings remain active.
