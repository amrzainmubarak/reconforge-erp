# Grouped matching 10K-record tier v1

Date: 2026-08-02 (Africa/Cairo)

Profile: `grouped-matching/10k-record-true-many-to-many-v1`

| Declared input | Value |
| --- | ---: |
| Partitions | 2,500 |
| Records per partition | 4 |
| Total records | 10,000 |
| Mode | true many-to-many |
| Search evaluations | 2,500 (one bounded 2x2 evaluation per partition) |

Environment: Windows 11 (`10.0.26200`), Python 3.14.6, AMD64, 16 logical
CPUs, one Python process. Every partition ran through
`GroupedSubsetSumStrategy` and the application service; every 100th partition
also ran with reversed input order.

| Run | Runtime (s) | Peak memory (MiB) | Matched | Ambiguous | Unmatched | Cross-engine mismatches | Permutation mismatches |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 4.1493 | 0.7991 | 2,500 | 0 | 0 | 0 | 0 |
| 2 | 4.1200 | 0.7785 | 2,500 | 0 | 0 | 0 | 0 |

Both runs produced the same effect digest
`a6089d61b21e4b47ecff2554cd5116186c675be7b9aa5b0686ebba1974e1bc84` and
manifest digest
`0568cc8472d85ce72e19bfb8ff119f03e5d1e8619dc77b4c3d7db3476c25e46f`.

Limitations: exact USD synthetic groups only; FX, fees, partial settlement,
dense ambiguity, provider I/O, PostgreSQL runtime parity, distributed load,
soak, and 100K/1M records remain unverified.
