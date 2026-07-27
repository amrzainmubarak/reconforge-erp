# ADR 0089: Bound PostgreSQL reconciliation JSONB objects

- Status: Accepted
- Date: 2026-07-26
- Decision owners: Financial Integrity, Platform Architecture, Security, Reliability
- Scope: FI-013 PostgreSQL reconciliation rules, input attributes, decision lineage, exception evidence, and worker consumption

## Context

PostgreSQL reconciliation persists four object-valued fields: `rule_json`,
`attributes_json`, `lineage_json`, and `evidence_json`. Their writers used a
local canonical encoder, but only attributes had a 100,000-byte check. Repository
and worker readers accepted driver mappings or used three direct `json.loads`
calls without duplicate-key, non-finite, graph, or resource enforcement.
Malformed state could therefore be returned publicly, supplied to the matcher,
or hashed after unbounded parsing. JSONB display whitespace also differs from
the compact rule bytes used by idempotency fingerprints.

## Decision

Publish `postgres-reconciliation-object-v1` and four named profiles:

- `postgres-reconciliation-rule-json-v1`,
  `postgres-reconciliation-lineage-json-v1`, and
  `postgres-reconciliation-evidence-json-v1` allow at most 4,194,304 UTF-8
  bytes, 100,000 nodes, depth 32, 25,000 items in one collection, and 262,144
  characters in one scalar;
- `postgres-reconciliation-attributes-json-v1` preserves the existing
  100,000-byte producer ceiling and applies the same node/depth/collection
  ceilings with 100,000 characters per scalar;
- all four require an object root, unique string keys, finite JSON values, and
  canonical sorted compact ASCII producer and consumer text;
- finite JSON numbers remain readable for historical non-financial display
  compatibility. Financial values remain exact text or integer minor units
  under their domain contracts;
- producers reject invalid, cyclic, non-object, non-finite, or over-budget
  values before persistence SQL. Partition lineage/evidence are preflighted
  before output hashing or the run lock;
- repository records decode all four fields before public return. Corruption is
  an integrity failure, never a replacement or sentinel object;
- both reconciliation worker decoding paths use the same profiles. A corrupt
  rule fails while reading the run before a claim update or matcher invocation;
- JSONB text is decoded and re-encoded canonically before idempotency
  fingerprinting so established valid rule bytes and digests remain stable;
- the exact direct-parser inventory removes all three reconciliation
  `json.loads` calls.

## Consequences

Three FI-013 direct calls remain: generic database export, Redis sessions, and
SQLite matching rules. One central bounded parser and one packaged
currency-registry parser account for the other two direct calls.

Encoding and decoding add bounded linear traversal and canonical serialization.
The ceilings are safety budgets, not supported throughput claims. Live
PostgreSQL rollback, driver-specific mapping behavior, and multi-worker runtime
remain unproved where service tests are skipped.

## Compatibility and migration

No table migration, API/CLI route, result identity, checkpoint identity, or
matching digest formula changes. Existing finite object JSONB rows remain
readable and returned as objects, matching normal PostgreSQL driver behavior.
The prior attributes byte ceiling remains exact. Malformed or oversized rows
that were previously parsed or returned permissively now fail visibly.

## Rollback

Revert the four profiles, shared schema, repository/worker routing, tests,
inventory, and governance as one unit. Existing valid rows remain ordinary
JSONB objects readable by the prior implementation. Do not rewrite or delete
runs, inputs, results, exceptions, checkpoints, audit rows, or outbox rows.
