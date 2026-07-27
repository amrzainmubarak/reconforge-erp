# ADR 0088: Bound PostgreSQL transactional-outbox payload JSON

- Status: Accepted
- Date: 2026-07-26
- Decision owners: Platform Architecture, Financial Correctness, Security, Reliability
- Scope: FI-013 PostgreSQL outbox payload producers, repository consumers, claims, and external publication handoff

## Context

The PostgreSQL ledger, master-data, close, evidence, and reconciliation
repositories write six call sites into one transactional outbox. The delivery
repository decoded JSONB mappings permissively and wrapped a non-object root as
`payload_value`. Producers used several direct or generic encoders without one
resource, duplicate-key, root-shape, or non-finite-value contract. A corrupt
claimed row could therefore become plausible publisher input, and producer
coverage could not be proven as one end-to-end contract.

The E-072 audit-metadata evidence also overstated producer coverage: ledger and
close used the bounded audit encoder, but master-data, evidence, and
reconciliation retained local encoders. This slice corrects the implementation
and the historical evidence boundary rather than carrying that gap forward.

## Decision

Introduce `postgres-outbox-payload-json-v1` and the recursive
`postgres-outbox-payload-object-v1` schema:

- object root, unique string keys, finite JSON values, and canonical sorted
  compact ASCII producer/publisher text;
- at most 4,194,304 UTF-8 bytes, 100,000 nodes, depth 32, 25,000 items in one
  collection, and 262,144 characters in one scalar;
- reject cycles, non-finite values, duplicate keys, invalid/non-object values,
  and excess resources with stable path/value-free internal codes;
- retain finite JSON number compatibility for historical non-financial payload
  fields; new financial event fields must remain exact text or integer minor
  units under their domain contracts;
- route all six producer call sites in five PostgreSQL repository families
  through the shared encoder before audit/outbox evidence SQL;
- decode either driver mappings or JSONB text under the same consumer contract
  and provide canonical `payload_json` to publishers;
- fail list and claim closed for corrupt rows. Because decoding occurs inside
  the claim transaction, failure rolls back the lease and attempt increment
  before any external publisher receives the event;
- retain tenant scope, event IDs, aggregate IDs, statuses, lease/retry/dead-letter
  transitions, JSONB storage, and `ON CONFLICT` idempotency behavior;
- route the remaining PostgreSQL audit writers through `audit-metadata-json-v1`
  and enforce exact producer-call inventory for both tables.

## Consequences

The PostgreSQL outbox direct `json.loads` call leaves the exact AST allowlist.
Six FI-013 direct calls remain across generic export, reconciliation, Redis,
matching, and two reconciliation-worker paths. One central bounded parser and
one packaged currency-registry parser account for the other two direct calls.

Encoding and decoding add bounded linear graph traversal and canonical
serialization. The 4 MiB ceiling is a safety budget, not a throughput or
delivery-latency claim. Live PostgreSQL/publisher failure behavior still
requires service-backed execution.

## Compatibility and migration

No table migration, event identity formula, API/CLI route, worker setting, or
valid payload shape changes. Existing finite object JSONB rows remain readable
and publishers receive the same compact sorted representation. Malformed,
duplicate-key text (where a non-JSONB test adapter supplies it), scalar/list,
non-finite, cyclic, or over-budget values now fail visibly rather than being
wrapped or published.

## Rollback

Revert all producer wrappers, the outbox consumer, shared profile/schema,
inventory contracts, tests, and governance as one unit. Existing canonical
rows remain ordinary JSONB objects readable by the prior implementation. Do not
delete, rewrite, publish, or reset outbox/audit rows during rollback.
