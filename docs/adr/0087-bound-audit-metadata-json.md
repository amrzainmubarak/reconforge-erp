# ADR 0087: Bound SQLite and PostgreSQL audit metadata JSON

- Status: Accepted
- Date: 2026-07-26
- Decision owners: Platform Architecture, Financial Correctness, Security
- Scope: FI-013 audit metadata producers, list/verifier consumers, and SQLite public export

## Context

SQLite and PostgreSQL audit ledgers accepted arbitrary unbounded metadata JSON.
Their readers converted malformed JSON into `invalid_metadata_json` and
non-object roots into `metadata_value`. That fallback could present corrupt
stored evidence as a plausible application object. SQLite hashes the exact
stored metadata text. PostgreSQL stores JSONB but historically hashes the
canonical compact text supplied before JSONB insertion, so PostgreSQL's rendered
text cannot be substituted directly without breaking valid historical hashes.

## Decision

Introduce `audit-metadata-json-v1` and the recursive
`audit-metadata-object-v1` schema:

- object root, unique string keys, finite JSON values, and canonical sorted
  compact ASCII producer text;
- at most 4,194,304 UTF-8 bytes, 100,000 nodes, depth 32, 25,000 items in one
  collection, and 262,144 characters in one scalar;
- reject cycles, non-finite values, invalid structures, duplicate keys, and
  excess resources with stable path/value-free internal codes;
- retain finite JSON number compatibility for historical non-financial metadata;
  financial amounts must continue to use established exact text or minor units;
- SQLite verification hashes exact stored text and independently validates its
  metadata contract;
- PostgreSQL verification decodes JSONB-rendered text and reconstructs the
  historical canonical producer text before hashing, while invalid metadata is
  an independent integrity issue;
- list consumers fail closed instead of inventing sentinel objects, and SQLite
  public export refuses invalid audit metadata before writing output files.

## Consequences

Three audit-specific direct `json.loads` calls leave the exact AST allowlist.
FI-013 remains partial: the generic export decoder plus PostgreSQL outbox and
reconciliation, Redis, matching, and worker values retain separate contracts.
The 4 MiB ceiling is a safety budget, not supported-throughput evidence.

## Compatibility and migration

No database migration, API route, CLI command, event-hash payload key, or valid
canonical producer byte changes. SQLite valid historical rows retain exact hash
bytes. PostgreSQL valid historical rows retain the compact canonical bytes used
when their hashes were created even though JSONB display adds whitespace.
Malformed, duplicate-key, non-object, non-finite, or over-budget metadata now
fails visibly; ReconForge does not silently rewrite those rows.

## Rollback

Revert the audit call sites and shared audit profile, schema, inventory entries,
tests, and documentation together. Canonical rows remain ordinary JSON objects
readable by the prior implementation. Do not rewrite audit rows, ledger heads,
or event hashes during rollback.
