# Grouped matching 1M tier v1

Date: 2026-08-02 (Africa/Cairo)

## Workload

The profile contains 1,000,000 exact-USD records arranged as 250,000
independent true many-to-many partitions. Each partition has two left records
(30 and 70) and two right records (25 and 75). Every partition is evaluated
through `GroupedSubsetSumStrategy` and `GroupedMatchingApplicationService`;
every 10,000th partition is replayed with reversed input order.

Profile ID: `grouped-matching/1m-record-true-many-to-many-v1`

## Observed result

| Measurement | Run 1 | Run 2 |
| --- | ---: | ---: |
| Partitions | 250,000 | 250,000 |
| Records | 1,000,000 | 1,000,000 |
| Matched partitions | 250,000 | 250,000 |
| Ambiguous / unmatched | 0 / 0 | 0 / 0 |
| Strategy evaluations | 250,000 | 250,000 |
| Cross-engine mismatches | 0 | 0 |
| Permutation mismatches | 0 | 0 |
| Runtime (seconds) | 433.3014 | 427.1993 |
| Peak traced memory (MiB) | 77.5718 | 77.5585 |

Environment: Windows 11 `10.0.26200`, Python `3.14.6`, AMD64, 16 logical CPUs.

Effect digest (both runs):
`05c76d8c2d30dcf8e85893ce777f5edc27324beb0465538fc76c2e6ea1c4124f`.

Manifest digest (both runs):
`5da7ca5deeeddb1f8d4ee04c23b4d4f79a33b34c6cf2861bc1dbf50ccbc9f7be`.

## Interpretation boundary

This is reproducible synthetic algorithm evidence for a partitioned,
single-process workload. It is not a distributed capacity result, SLO, or
production readiness claim. PostgreSQL runtime parity, soak/failure load,
provider I/O, FX/fees/partial settlement, ambiguity density, and domain-diverse
financial workloads are not covered. The published per-partition record and
search-evaluation ceilings remain active; this does not prove unbounded
many-to-many search.
