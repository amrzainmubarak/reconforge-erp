# ADR 0042: Version Multiset Record Identity and Source Location

- Status: Accepted
- Date: 2026-07-25
- Scope: Stock/GL and deterministic platform matching identity, lineage, and signatures

## Context

Stable business-field fingerprints removed DataFrame index identity from normal
stock/GL matching, but two byte-equivalent records still shared the same match
identifier. Data-quality evidence also used `source_row` without defining
whether it identified a record or only described where one ingestion happened
to observe it. DuckDB partition replay, Pandas execution, local CSV jobs, and
hosted canonical records therefore could not make the same bounded claim about
duplicate identity.

Physical copies of truly identical records cannot be distinguished after a
permutation unless the source supplies an intrinsic identifier. Inventing that
distinction from a row index would make replay order part of business identity.
At the same time, discarding an available CSV row would weaken operator
diagnostics.

## Decision

Adopt `canonical-multiset-occurrence-v1` for current reconciliation writers:

1. Canonicalize each record's non-internal fields and hash them into an
   equivalence-class fingerprint. Existing business identifiers remain part of
   that canonical record; reserved `_reconforge_*` fields never participate.
2. A singleton uses its canonical fingerprint identity. Equivalent duplicates
   receive deterministic instance identifiers ending in `#occurrence:1`,
   `#occurrence:2`, and so on. The stable output is the multiset of instance
   identifiers. No claim is made that occurrence 1 denotes the same physical
   copy after identical rows are reordered.
3. Persist `record_instance_id`, `record_fingerprint`, `duplicate_ordinal`,
   `duplicate_count`, and `record_identity_policy` in matched, unmatched, and
   data-quality lineage. Match and exception identity include record-instance
   identity so duplicate copies do not collapse.
4. Treat source location as mutable evidence, never identity. For tabular CSV
   and stock/GL inputs, `source_position` is one-based data-record position and
   `source_row` is the one-based physical row including the header, so the first
   data row is 2; its basis is `tabular-header-offset-v1`. Local JSON uses
   `json-record-position-v1` and has no tabular row. Hosted/in-memory canonical
   records without trusted location use null position/row and
   `source-location-unavailable-v1`; the matcher does not invent one from query
   order. User-supplied reserved lineage fields are ignored at public ingress.
5. Exclude source location from exception IDs and deterministic decision
   signatures. Relocating the same record may update diagnostic evidence but
   must not create another business exception or decision.
6. Make `reconciliation-signature-v3` the Pandas/DuckDB writer. V3 retains v2's
   exact financial-cell rules, includes record-instance/duplicate policy
   fields, and omits source-row location from exception identity. Explicit v1
   and v2 readers remain for historical digest reproduction.
7. Current CLI, engine, enterprise-demo, report, and PostgreSQL API writers
   select the new policy. New server submissions reject another policy. Stored
   rules without the field are read as `row-order-occurrence-legacy-v0` and are
   not relabeled as canonical historical evidence. Local idempotency keys
   cannot cross policies.
8. Advance the management pack to schema v3. The closed schema keeps explicit
   v1 and v2 compatibility branches that require the fields those versions
   actually contained and reject later policy fields.

## Consequences

- Duplicate-identical inputs produce distinct match/exception instance IDs and
  one stable decision multiset under row permutations.
- Operators retain trustworthy CSV row diagnostics while parity digests remain
  insensitive to file relocation.
- A caller must compare decision identity separately from mutable location
  evidence. Full serialized evidence may correctly differ when a row moves.
- Historical v1/v2 digests and missing-policy rules remain interpretable, but
  they do not acquire a guarantee they never recorded.
- This policy does not solve probabilistic identity, cross-file entity
  resolution, all matching strategies, supported-Python parity, or live
  PostgreSQL/DuckDB version matrices.

## Rollback

Readers may reproduce an explicitly versioned v1/v2 signature or execute a
stored legacy rule under its recorded label. Current writers must not silently
drop occurrence identity, include source rows in decision identity, trust
caller-supplied reserved fields, reuse an idempotency key across policies, or
relabel historical evidence. A rollback of a current writer requires retaining
the v3 digest/policy and emitting a separately versioned artifact.
