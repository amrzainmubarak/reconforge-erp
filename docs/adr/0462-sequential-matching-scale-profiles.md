# ADR 0462: Partitioned sequential matching scale profiles

- Status: accepted
- Date: 2026-08-09
- Decision owner: ReconForge execution owner

## Context

The repository already publishes grouped-matching 10K/100K/1M observations,
but the bounded sequential portfolio had no comparable reproducible scale
profile. A single unpartitioned sequence search would exceed its explicit
candidate budget and would be an invalid scale test.

## Decision

Publish three partitioned synthetic profiles with exactly 10,000, 100,000,
and 1,000,000 records. Every small partition cycles carry-forward,
contiguous sequence-window, and reversal-pairing inputs. The profile records
runtime, traced peak memory, effect/manifest digests, explicit unmatched rows,
permutation checks, mutation detection, and sampled PostgreSQL-worker adapter
parity. The 10K tier checks every partition; 100K and 1M use declared sample
strides to keep the measurement bounded.

## Rationale and boundaries

Partitioning preserves the strategy's finite per-partition search budget and
avoids a misleading cross-partition Cartesian product. The reports are
version-controlled one-host algorithm observations only. They do not establish
distributed capacity, PostgreSQL runtime parity, provider behavior, soak,
SLO/RPO/RTO, or financial posting.

## Reversibility

Removing the benchmark, reports, docs, and focused tests is code-only and does
not alter migrations, persisted schemas, or external systems.

## Verification

`tests/test_sequential_matching_scale.py` verifies the 10K run, declared
100K/1M shapes, report digests, and distribution membership. Each report is
generated from the corresponding public function and carries its environment
and limitations.
