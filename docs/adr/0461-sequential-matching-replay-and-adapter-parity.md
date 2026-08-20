# ADR 0461: Replay and adapter parity for sequential matching

- Status: accepted
- Date: 2026-08-09
- Decision owner: ReconForge execution owner

## Context

The bounded `carry-forward`, `sequence-window`, and `reversal-pairing`
strategies have domain and worker-projection contracts, but their durable-job
checkpoint and retry behavior was not exercised as one replayable matrix.
Without that matrix, a worker restart could theoretically duplicate an
allocation or detach the PostgreSQL-worker projection from the public strategy
digest.

## Decision

Add a synthetic, bounded replay profile that runs one partition for each
sequential mode through the public strategy and the PostgreSQL-worker adapter.
Persist each partition as a durable SQLite job effect, inject one retry after
each non-terminal checkpoint, and require:

- the interrupted effect digest equals an uninterrupted baseline;
- zero duplicate partition effects and no queued/running residue;
- the adapter's lineage strategy-result digest equals the direct strategy
  digest;
- a one-cent adversarial mutation changes the output digest.

The profile is a correctness/replay contract, not live PostgreSQL evidence,
throughput, HA/DR, or a scale claim. The strategy remains proposal/evidence
logic and cannot post financial effects.

## Rationale

This makes crash/resume and projection parity executable without conflating a
single-host synthetic SQLite run with an independent PostgreSQL deployment.
It provides a deterministic regression gate while preserving the explicit
external-service boundary for hosted runs.

## Reversibility

Code, test, benchmark, and documentation removal is reversible. No migration,
external provider, or persisted production schema changes are introduced.

## Verification

`tests/test_sequential_matching_replay.py` runs the profile and every
non-terminal fault point. The profile is distributed as
`reconforge/benchmark/sequential_matching_replay.py`; live PostgreSQL parity,
large-scale performance, and production recovery remain open.
