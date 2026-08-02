# ADR-0231: Publish a partitioned 100K grouped-matching tier

- Status: accepted
- Date: 2026-08-02

## Context

The advanced matching workstream needs a larger reproducible observation while
preserving deterministic, explainable, bounded search. A single unbounded
100K-group search would not be a safe benchmark or a production claim.

## Decision

Publish `grouped-matching/100k-record-true-many-to-many-v1` as 25,000
independent four-record partitions. Execute each partition through the public
strategy adapter and backend-neutral application service. Sample every 1,000th
partition under reversed input order and require identical effect and manifest
digests across complete runs.

## Evidence

Two Windows 11/Python 3.14.6 runs matched all 25,000 partitions with zero
ambiguity/unmatched results, zero adapter/application mismatches, and zero
permutation mismatches. Runtime was 42.0286s and 40.7803s; traced peak memory
was 7.7915 MiB and 7.7700 MiB. Both runs produced effect digest
`dda82223212af64038094cc21d4a6fed08af76d86a5b9920c1f4bd187d33be41` and
manifest digest
`60aad17ab30533964f61e1b5c64aeba58e56915ee62ac5a75325c25a7133981a`.

## Consequences and limits

This closes only the declared 100K partitioned algorithm observation. It does
not establish PostgreSQL parity, distributed capacity, SLOs, soak, provider
I/O, financial-domain diversity, or 1M performance. No schema or external
state changes.
