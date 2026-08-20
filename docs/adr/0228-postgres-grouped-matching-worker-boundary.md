# ADR 0228: PostgreSQL grouped matching stays in the worker boundary

## Status

Accepted as a contract-only adapter slice.

## Context

The grouped matcher is pure and deterministic, while the PostgreSQL worker
owns streaming, leases, checkpoints, and result persistence. Treating the
grouped algorithm as a database repository would duplicate financial logic and
make the local-first path diverge.

## Decision

Add `PostgresGroupedMatchingAdapter` as a persistence-free partition matcher.
It translates tenant-scoped streamed rows into the closed grouped strategy
request, rejects implicit modes and binary tolerances, skips committed
checkpoints, converts Decimal output to deterministic JSON text, and returns
the existing `ReconciliationPartitionResult` contract. The PostgreSQL worker
remains responsible for all database I/O and durable effects.

## Boundary

Focused tests prove adapter behavior and permutation stability, not a live
PostgreSQL grouped-match run. The parity inventory therefore records this
adapter as `contract_only`; no PostgreSQL production-parity claim is made.

## Rollback

Remove the adapter, tests, ADR, manifest, inventory, and execution evidence.
No migration or production data changes are involved.
