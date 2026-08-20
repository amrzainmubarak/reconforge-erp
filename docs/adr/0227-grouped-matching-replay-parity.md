# ADR 0227: Grouped matching replay must preserve cross-engine decisions

## Status

Accepted for the bounded synthetic replay slice.

## Context

The grouped matcher has bounded one-to-many, many-to-one, many-to-many,
portfolio, and partial-settlement paths. Existing unit tests prove individual
decisions and permutation stability, but a durable partition retry must also
prove that persisted effects reproduce an uninterrupted run and that the
strategy adapter agrees with the application boundary.

## Decision

Add `reconforge.benchmark.grouped_matching_replay` with four synthetic
partitions. Each partition is evaluated through `GroupedSubsetSumStrategy` and
`GroupedMatchingApplicationService`, then committed through the existing
durable-job checkpoint/effect boundary. A fault after the first partition
forces one retry; the replay digest, cross-engine decision digests, and a
one-cent adversarial mutation sentinel are required to agree.

## Boundaries

The profile is SQLite-only and bounded to four partitions. It does not claim
PostgreSQL matcher parity, mutation-tool score, or 10K/100K/1M capacity.

## Rollback

Remove the replay harness, tests, ADR, benchmark documentation, manifest entry,
and execution evidence. No schema or production behavior changes.
