# ADR 0127: Bounded and audited Evidence Graph drill-down

- Status: Accepted
- Date: 2026-07-28

## Context

Evidence readers need to traverse from an evidence record to governed objects and peer
evidence. Returning an unrestricted graph can exhaust resources, expose filesystem or
storage provenance, and leave sensitive access invisible. SQLite Community mode and
tenant-scoped PostgreSQL mode also need equivalent observable semantics.

## Decision

Use one additive API contract across both repositories:

- close direction to `up`, `down`, or `both` and depth to 1-8;
- fail closed above 10,000 discovered nodes;
- return deterministic offset pages of at most 1,000 nodes;
- define returned edges as all edges incident to the returned nodes and expose that
  scope in pagination metadata;
- mask path, checksum, source reference, storage, size, retention, and content metadata
  by default;
- require `evidence.manage` before `include_sensitive=true`; and
- append a hash-chained access-audit event for successful reads without publishing a
  business outbox event.

## Consequence

P2-002 has a bounded code-level SQLite/PostgreSQL contract with role and audit tests.
Offset pagination is adequate for the current bounded local contract; cursor pagination
requires measured need. Authenticated manifest serving, graph UI, live PostgreSQL
operating evidence, and graph throughput remain outside this ADR.

## Reversibility

The route and query fields are additive. Default limits may be reduced safely. Increasing
ceilings requires performance evidence; weakening masking or audit behavior requires an
explicit security decision and migration notice.
