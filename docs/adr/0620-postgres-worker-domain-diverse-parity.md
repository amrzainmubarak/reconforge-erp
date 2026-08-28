# ADR 0620: Add a domain-diverse PostgreSQL worker parity profile

- Date: 2026-08-24
- Status: accepted
- Scope: in-process grouped PostgreSQL worker-adapter replay evidence

## Context

The existing `postgres-worker-strategy-parity-v1` profile covered five grouped
and three sequential modes with one bounded fixture. The live PostgreSQL
domain-diverse runtime profile exercises six materially different grouped
shapes—cardinality changes, fee-aware portfolio netting, FX conversion, and
partial settlement—but its runtime artifact does not itself prove that every
shape projects the same deterministic decision digest as the direct strategy.

## Decision

Add the additive `postgres-worker-domain-diverse-parity-v1` profile. It runs
the grouped worker adapter and direct `GroupedSubsetSumStrategy` over six
explicit synthetic fixtures:

- one-to-many;
- many-to-one;
- true many-to-many;
- fee/net-aware portfolio;
- FX-aware many-to-many; and
- partial-settlement portfolio.

For every fixture the profile requires a matching direct/projected decision
digest and a stable result under left/right record permutation. The profile
emits a deterministic digest and a checked-in JSON artifact, but remains an
in-process contract check; it must not be described as live PostgreSQL,
cross-engine, capacity, provider, or production evidence.

## Consequences

- Domain-diverse grouped shapes now have direct strategy-to-worker projection
  evidence in addition to the hosted runtime selector.
- The existing eight-case v1 profile and its digest remain unchanged, so
  downstream consumers do not need a migration.
- The artifact is indexed with `partial` status and an explicit claim boundary.
- Live database execution, exchange-rate source validation, provider I/O,
  cross-host behavior, and production sizing remain separate gates.

## Reversibility

The additive profile and artifact can be removed without changing strategy,
worker, schema, or API behavior. Any change to the fixture inventory or digest
must use a new profile version and update its evidence index entry.
