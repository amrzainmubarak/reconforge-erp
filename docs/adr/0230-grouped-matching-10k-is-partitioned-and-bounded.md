# ADR 0230: Publish a partitioned 10K grouped-matching tier

- Date: 2026-08-02
- Status: accepted

## Decision

Publish a 10,000-record grouped-matching profile made of 2,500 independent
true many-to-many partitions with four records each. Execute every partition
through the public strategy adapter and the backend-neutral application
service, and sample deterministic input permutations. Keep each partition
inside the strategy's published cardinality and search ceilings.

## Evidence boundary

The profile proves exact USD synthetic matching, cross-engine adapter parity,
zero ambiguity/unmatched partitions, permutation stability, and reproducible
structural/effect digests on one Windows host. It does not prove FX/fee/partial
settlement density, PostgreSQL runtime, distributed throughput, soak, or
100K/1M capacity.

## Rollback

Remove the benchmark module, tests, report, ADR, and manifest entries. No
schema or external state is changed.
