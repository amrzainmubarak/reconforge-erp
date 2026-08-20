# ADR 0268: PostgreSQL grouped matching runtime parity

## Status

Accepted as a bounded worker-runtime parity slice.

## Context

ADR 0228 deliberately kept grouped matching in a persistence-free worker
adapter, but its internal `GroupedMatchDecision` payload did not fit the
existing PostgreSQL reconciliation result/exception tables. That meant the
adapter could be unit-tested yet could not safely complete a real leased,
checkpointed PostgreSQL run.

## Decision

Project each grouped decision into the existing per-source result contract:

- a matched group emits the deterministic Cartesian edge set so every source
  identity is represented and the complete-run invariant remains valid;
- unresolved groups emit single-sided `Ambiguous`/`Unmatched` rows and bounded
  review exceptions, never silently selecting a candidate;
- full group totals, identities, policy, strategy manifest/input/result digests,
  and explanation metadata remain in validated lineage JSON;
- PostgreSQL-owned canonical columns override JSON attributes for identity,
  amount, date, currency, and partition;
- the existing worker continues to own leases, checkpoints, audit/outbox, and
  all database writes.

Add one live server-boundaries contract using synthetic Decimal records,
non-superuser RLS, the real PostgreSQL worker, and a direct strategy digest
comparison. The contract asserts completion, exact edge cardinality, lineage,
checkpointing, and sibling-tenant isolation.

## Boundary

This proves one small PostgreSQL runtime path for the bounded grouped strategy;
it does not prove the full Matching Application repository, 10K/100K/1M
PostgreSQL scale, soak/backpressure, distributed capacity, HA/DR, live ERP or
bank data, or posting/write-back.

## Rollback

Remove the projection helpers, runtime contract, ADR, and execution evidence.
No migration, production data, provider call, or schema change is required.
