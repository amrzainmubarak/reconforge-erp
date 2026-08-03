# ADR 0291: Exercise carry-forward and reversal pairing through the PostgreSQL worker

- **Status:** Accepted (bounded E-340 slice)
- **Date:** 2026-08-03
- **Decision owners:** ReconForge maintainers

## Context

`bounded-carry-forward-fifo` and `bounded-reversal-pairing` were deterministic
experimental strategies with local contracts, while the PostgreSQL worker
runtime only exercised grouped matching. This left sequence allocation,
residuals, and explicit reversal links outside the hosted checkpoint/result
boundary.

## Decision

Add a persistence-free PostgreSQL worker adapter with explicit rule modes
`carry-forward`, `sequence-window`, and `reversal-pairing`. It translates
tenant-scoped inputs into the existing strategy requests and projects
allocations/pairs, unmatched records, residuals, explicit-link basis, strategy
digests, and bounded ambiguities into the existing result/exception schema.

The live server-boundary contract runs one carry-forward case (`100` obligation
against `60` settlement, residual `40`) and one explicit reversal pair (`100`
against `-100`), then compares persisted result digests with direct strategy
execution.

## Boundary

This is synthetic single-node PostgreSQL worker evidence. It does not prove
posting, compensation, external write-back, large-scale sequence performance,
live provider data, HA/DR, or production readiness.

