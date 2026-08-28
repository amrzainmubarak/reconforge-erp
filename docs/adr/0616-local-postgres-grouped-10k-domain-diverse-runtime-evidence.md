# ADR 0616: Current local PostgreSQL grouped 10K domain-diverse runtime evidence

Status: Accepted

## Context

The existing PostgreSQL grouped 10K profile exercised a homogeneous five-mode
fixture. The architecture and matching evidence require domain diversity across
cardinality, netting, FX, fee, and unresolved partial-settlement behavior, but
must not turn one workstation run into a capacity or production claim.

The first live domain-diverse attempts exposed two correctness issues. A stale
worker could observe a database row with `status=Running` after the durable
execution had already become terminal, then try to persist a failure over the
completed run. The domain one-to-many and many-to-one fixtures also require
three projected result edges per primary record, so an allowance of two was
incorrect for those bounded shapes.

## Decision

Retain `postgres-grouped-matching/10k-domain-diverse-v1` as bounded local
runtime evidence. It cycles six explicit synthetic shapes over 16 independent
workers, 250 runs, ten partitions per run, 2,500 partitions, and exactly
10,000 source records. The profile requires 9,160 persisted result rows,
zero duplicate result identities, zero failed runs, zero final active runs,
and mode-derived completion counts.

Make the durable execution state authoritative in `claim_run`: terminal
`Complete`, `Failed`, or `Cancelled` execution states are treated as a busy
or stale claim before the legacy status field is considered. This preserves
the existing retry/skip contract and prevents a stale worker from overwriting
terminal evidence. Keep the fixture allowance at three only for the two
three-edge one-to-many/many-to-one shapes; all other domain-diverse shapes use
the normal bounded allowance of two.

The accepted local observation is 250/250 runs, 2,500/2,500 partitions,
9,160/9,160 rows, zero duplicate/failure/active outcomes, and 63.9503 seconds
on Windows 11/Python 3.14.6/AMD64 with PostgreSQL 16.14. The effect and
manifest digests are retained in the companion JSON artifact.

## Consequences

- The source, focused contracts, workflow selector, JSON report, and benchmark
  note now preserve a reproducible domain-diverse correctness gate.
- The race regression is covered by
  `tests/test_postgres_reconciliation.py` and the six fixture projections are
  covered by `tests/test_postgres_grouped_matching_scale.py`.
- The result remains one-host synthetic runtime evidence. It does not claim
  throughput, capacity, SLO, soak, cross-host fairness, queue HA, automatic
  failover, HA/DR, provider interoperability, statutory posting, write-back,
  or production sizing.

## Reversibility

Revert the profile, fixture, race regression, workflow selector, and evidence
artifacts as one change. No database migration or persistent schema change is
introduced by this ADR.
