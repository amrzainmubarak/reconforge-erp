# ADR 0090: Bound SQLite matching-rule JSON

- Status: Accepted
- Date: 2026-07-26
- Decision owners: Financial Integrity, Platform Architecture, Security, Reliability
- Scope: FI-013 SQLite `match_jobs.rule_json` and `match_rules.rule_json`

## Context

The local matching service writes one rule object to both matching tables and
later decodes the job copy for idempotent replay. The producer used ordinary
`json.dumps` and the replay path used a direct `json.loads`, with no byte,
graph, duplicate-key, non-finite, or root-shape contract. Public job readers
also returned stored text without first detecting corruption. The exact spaced
sorted ASCII representation is established compatibility state and contains
the persisted financial-input and record-identity policy choices.

## Decision

Publish `sqlite-matching-rule-object-v1` and the named
`sqlite-matching-rule-json-v1` profile:

- allow at most 4,194,304 UTF-8 bytes, 100,000 nodes, depth 32, 25,000 items in
  one collection, and 262,144 characters in one scalar;
- require an object root, unique string keys, finite JSON values, and the
  historical sorted ASCII producer representation with default JSON spacing;
- reject binary floats, non-finite values, cycles, invalid roots, and resource
  excess in new producer input. Historical finite JSON floats remain readable
  only for backward compatibility; matching financial values remain governed
  by the stored financial-input policy;
- encode once before `BEGIN IMMEDIATE`, then bind the identical text to both
  tables. Producer failure therefore occurs before transaction or business,
  audit, and outbox effects;
- decode idempotency replay through the same bounded profile and retain the
  historical missing-policy defaults. Corruption fails before a new matching
  effect;
- validate stored rule text before `job_status` and `list_jobs` return it, but
  preserve the raw valid text in those public compatibility shapes;
- remove the SQLite matching direct parser from the exact AST allowlist.

## Consequences

Two FI-013 direct calls remain: generic database export and Redis sessions. One
central bounded parser and one packaged currency-registry parser account for
the other two direct calls.

Encoding and decoding add bounded linear traversal and serialization. The
ceilings are safety budgets, not supported throughput claims. The rule schema
is structural and does not prove business-semantic validity or stored-row
authenticity.

## Compatibility and migration

No database migration, route, CLI, rule field, job/result identity, matching
digest, or idempotency-key formula changes. Valid historical spaced rule text
continues to be stored and returned byte-for-byte. Existing rows without the
two policy fields replay with the established legacy defaults. Malformed,
ambiguous, non-finite, non-object, or oversized stored values that were
previously accepted or exposed now fail visibly.

## Rollback

Revert the profile, schema, matching-service routing, tests, inventory, and
governance as one unit. Existing valid rows remain ordinary JSON text readable
by the prior implementation. Do not rewrite or delete matching jobs, rules,
results, audit events, or outbox events.
