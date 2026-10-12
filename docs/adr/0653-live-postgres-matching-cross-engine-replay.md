# ADR 0653: Record live PostgreSQL matching cross-engine replay evidence

- Date: 2026-08-26
- Status: accepted
- Scope: one disposable PostgreSQL 16 `linux/amd64` runtime and the existing
  grouped/sequential worker contract

## Context

E-1003 already had deterministic pure-strategy and in-process worker
projection profiles. It did not yet have a fresh live PostgreSQL execution
that compared persisted worker lineage digests with the direct strategy
implementations across the grouped and sequential families.

## Decision

Retain the existing live integration test as the bounded E-923 evidence
surface. Run it against a disposable PostgreSQL 16 Alpine image bound to
`postgres@sha256:57c72fd2a128e416c7fcc499958864df5301e940bca0a56f58fddf30ffc07777`.
The evidence records four grouped runs (one-to-many, many-to-many, FX-aware,
and fee/partial portfolio) and four sequential runs (carry-forward,
sequence-window, equal-cost ambiguity, and reversal pairing). The test must
also pass direct-strategy digest assertions and a cross-tenant visibility
refusal.

## Consequences

- Live PostgreSQL worker persistence is now supported by a fresh local runtime
  observation, not only an in-process projection profile.
- The result remains synthetic, one-host, one-run evidence. It does not prove
  provider rate authenticity, posting/write-back, capacity, soak, HA/DR,
  hosted reproducibility, or production readiness.
- The temporary database and credentials are disposable test fixtures and are
  not release secrets.

## Reversibility

Remove the E-923 evidence record and ADR without changing application,
database, or matching contracts. Any wider claim requires a new bounded
profile, exact workload definition, and independent evidence.
