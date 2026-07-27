# ADR 0086: Bound AP/AR financial idempotency JSON

- Status: Accepted
- Date: 2026-07-26
- Decision owners: Platform Architecture, Financial Correctness, Security
- Scope: FI-013 AP/AR SQLite idempotency response producers and consumers

## Context

Accounts Payable and Accounts Receivable store complete operation responses as
JSON text so a repeated idempotency key returns the original result without a
second financial effect. Both writers used unrestricted `json.dumps(default=str)`
and both readers used unrestricted `json.loads`. Stored duplicates, non-finite or
fractional number tokens, deep/wide graphs, or oversized values were therefore
not governed consistently. A corrupt replay failed before the normal mutation,
but it had no explicit resource contract; a producer could also persist a value
that later decoded differently at a financial boundary.

The wider FI-013 inventory contains ten other direct parser calls across audit,
export, PostgreSQL, Redis, matching, and workers. They have different producers,
failure semantics, and compatibility requirements and are not silently grouped
into this decision.

## Decision

Introduce `financial-idempotency-json-v1` and the structural
`financial-idempotency-response-object-v1` schema:

- object root and unique string keys;
- at most 4,194,304 UTF-8 bytes, 100,000 nodes, depth 32, 25,000 items in one
  collection, and 262,144 characters in one scalar;
- JSON number tokens are integers only; exact fractional quantities remain text
  and monetary values remain integer minor units;
- non-finite values, binary-float producer values, cycles, invalid structures,
  and excess resources fail closed with stable path/value-free error codes;
- current producers emit deterministic ASCII JSON with sorted keys and compact
  separators, then parse it under the same consumer contract before insertion;
- AP/AR readers use the shared contract and retain the established public
  `PlatformError` wording;
- producer rejection occurs inside the existing SQLite transaction and triggers
  rollback; corrupt replay is rejected before a new AP/AR business mutation,
  audit event, or outbox event.

Historical valid object responses made of strings, integer tokens, booleans,
nulls, arrays, and objects remain readable. Historical fractional/exponent JSON
number tokens are rejected rather than converted to binary floats or silently
reinterpreted as exact financial values.

## Consequences

The two AP/AR direct `json.loads` calls leave the exact AST allowlist. FI-013
advances from excluded to partial, not complete. Backup/restore can preserve
these rows, while a restored corrupt or out-of-contract historical row remains a
visible replay failure. The remaining FI-013 producer/consumer pairs still lack
field-specific bounded schemas.

The producer preflight is linear in the in-memory response graph and canonical
encoding adds one bounded serialization plus parse. No throughput claim is made;
the 4 MiB ceiling is a safety limit, not a supported performance tier.

## Compatibility and migration

No table, API, CLI, key format, result object, or existing migration changes.
New rows use canonical text. Valid historical rows remain readable. Operators
with rejected historical rows must inspect and restore/recreate them from trusted
application evidence; ReconForge does not silently rewrite financial replay
state.

## Rollback

Revert the two platform call-site changes and remove the shared helper, schema,
inventory policy, and tests. Existing canonical rows are ordinary JSON objects
and remain readable by the prior code. Do not delete or rewrite idempotency rows
as part of rollback.
