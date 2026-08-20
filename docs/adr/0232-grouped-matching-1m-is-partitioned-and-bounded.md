# ADR-0232: Publish a partitioned 1M grouped-matching tier

- Status: accepted
- Date: 2026-08-02

## Context

The matching workstream explicitly requires a reproducible 1M benchmark before
any scale statement. The grouped search must remain bounded and explainable;
an unbounded cross-partition search would be neither safe nor meaningful.

## Decision

Publish `grouped-matching/1m-record-true-many-to-many-v1` as 250,000 independent
four-record partitions. Execute every partition through the public strategy
adapter and backend-neutral application service. Sample every 10,000th partition
under reversed input order and require identical effect and manifest digests
across complete runs.

## Evidence

Two Windows 11/Python 3.14.6 runs matched all 250,000 partitions with zero
ambiguity/unmatched results, zero adapter/application mismatches, and zero
permutation mismatches. Runtime was 433.3014s and 427.1993s; traced peak memory
was 77.5718 MiB and 77.5585 MiB. Both runs produced effect digest
`05c76d8c2d30dcf8e85893ce777f5edc27324beb0465538fc76c2e6ea1c4124f` and
manifest digest
`5da7ca5deeeddb1f8d4ee04c23b4d4f79a33b34c6cf2861bc1dbf50ccbc9f7be`.

## Consequences and limits

This closes only the declared 1M partitioned algorithm observation. It does
not establish PostgreSQL parity, distributed capacity, SLOs, soak, provider
I/O, financial-domain diversity, or production readiness. No schema or
external state changes.
