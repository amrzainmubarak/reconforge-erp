# ADR 0305: Publish a domain-diverse grouped-matching 10K profile

- Status: accepted
- Date: 2026-08-04
- Scope: `P4-MAT-001`

## Decision

Add `grouped-matching/10k-domain-diverse-v1`, a deterministic 2,500-partition
profile containing exactly 10,000 synthetic records. The partitions cycle
through one-to-many, many-to-one, true many-to-many, fee-aware portfolio
netting, FX-aware many-to-many, and partial-settlement portfolio cases. Every
partition runs through both the public `GroupedSubsetSumStrategy` adapter and
the backend-neutral application service.

The profile records adapter-digest equality, reversed-input permutation
equality, mode counts, bounded search evaluations, and a deliberate
ambiguous-result count for partial portfolios. The ambiguity is expected
evidence: the matcher must not invent a unique settlement when equal partial
choices remain.

## Rationale

Existing 10K/100K/1M profiles use a homogeneous exact USD many-to-many shape.
They prove partitioned deterministic execution but do not exercise FX, fees,
netting, or partial-settlement density at a declared scale. This profile
strengthens the algorithm evidence without changing strategy ceilings or
turning a workstation run into a capacity claim.

## Evidence boundary

The profile is one-host, one-process synthetic algorithm evidence. Carry-forward,
sequence/window, reversal, PostgreSQL runtime parity, soak, provider I/O,
distributed capacity, and production sizing remain separate gates. No journal
posting, settlement write-back, or statutory accounting is performed.

## Rollback

Remove the benchmark module, tests, docs, package entries, and execution
records. Existing grouped strategy behavior and homogeneous scale profiles are
unchanged.
