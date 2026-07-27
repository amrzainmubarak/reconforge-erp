# File ingestion boundary

ReconForge treats every operator-selected or generated file as untrusted. The current bounded implementation is intentionally narrow: the canonical reconciliation CSV/XLS/XLSX reader, mapping header inspection, DuckDB direct scans, the built-in generic CSV adapter, and client-pack CSV redaction pass through `tabular-file-ingress-v1` before a dataframe, DuckDB parser, or redaction writer receives content. Configuration, mapping, control-pack, Reconciliation-as-Code, close-workflow JSON/YAML, client-pack manifests, evidence-index manifests, and client-pack JSON redaction pass through `structured-document-ingress-v1` before object validation or redaction. Client-pack source enumeration, generic text redaction, non-redacted copying, and output-manifest rechecks use a separate fixed local redistribution budget recorded under FI-012.

The policy rejects non-regular files and symlinks, unsupported or mismatched extensions/content, oversized files and tables, malformed CSV shapes, oversized CSV fields, unsafe XLSX archive names and duplicates, unsupported compression, decompression bombs, DTD/entity declarations, external relationships, formulas, VBA, ActiveX, embeddings, and excess worksheet rows/cells. Client-pack CSV redaction additionally rejects duplicate headers, preserves exact field text, and streams one row at a time through per-file temporary replace. Client-pack generic text is strict UTF-8 and processed one bounded line at a time; non-redacted bytes are copied in bounded chunks with open-file change checks. Rejections expose a stable code without the local path or source value.

The structured-document policy accepts strict UTF-8 JSON/YAML within fixed byte, node, depth, collection, scalar, and YAML-alias budgets. JSON duplicate keys and non-finite constants fail closed. YAML duplicate keys, merge keys, cyclic objects, unsafe tags, non-finite constructed values, and multiple documents fail closed. Strict financial YAML continues to preserve decimal lexemes as text before domain validation. Client-pack strict JSON redaction likewise preserves fractional/exponent lexemes while legacy mode retains its finite-float behavior; predictable invalid JSON fails before fingerprint hashing or destination preparation instead of becoming text.

Local database restore applies the same duplicate-safe JSON engine through the
`database-backup-json-ingress-v1` profile to both `manifest.json` and
`backup.json`: 64 MiB per file, 1,000,000 nodes, depth 64, 250,000 collection
items, and an 8 MiB scalar ceiling. Bounded before/after fingerprints, closed
manifest/backup shapes, exact artifact checksum/byte/schema agreement, and a
registered table-name allowlist are checked before restore temporary-file
creation or target mutation. Missing registered tables remain allowed for
historical additive schema-v1 restores. The current implementation accepts no
backup archive.

Legacy account_reconciliations.json and control_tests.json DB imports use
database-legacy-import-json-ingress-v1: 16 MiB per file, 500,000 nodes, depth
32, 50,000 collection items, and a 1 MiB scalar ceiling. Stable regular
non-reparse reads, duplicate/non-finite rejection, and pre/post byte
fingerprints run before database inspection. Exactly one documented list
envelope, a direct list, an empty object, or an identifier-keyed object map is
accepted; ambiguous aliases and arbitrary objects no longer become implicit
empty imports. Parsed-byte SHA-256, size, and profile are retained as local
provenance. These unkeyed values do not authenticate the source or authorize
the import.

Platform business-record CSV/JSON imports use business-record-ingress-v1:
64 MiB per file, 250,000 records, 512 fields per record, 10,000,000 cells, and
128,000 characters per field/scalar; JSON additionally caps 2,000,000 nodes and
depth 32. Strict UTF-8, duplicate/non-finite rejection, exact fractional and
exponent lexemes, unambiguous list/envelope shapes, strict CSV headers/shape,
and stable pre/post fingerprints apply before domain mutation. Account,
control, intercompany, and journal evidence carries the digest, size, and named
profile of the parsed bytes. Service-specific validation still owns business
meaning, and unkeyed hashes do not authenticate or authorize an import.

Current local Studio CSV/JSON views use generated-artifact-ingress-v1: 64 MiB
per file, 250,000 CSV rows, 512 columns, 10,000,000 cells, and 128,000
characters per CSV field; JSON additionally caps 1,000,000 nodes, depth 64,
250,000 items per collection, and 1,000,000 characters per scalar. Strict
headers/encoding/shape, duplicate/non-finite rejection, exact JSON fractional
lexemes, reparse refusal, and stable pre/post fingerprints precede rendering.
Pandas `keep_default_na=False` typing remains for display compatibility. When a
companion JSON exists, its named object-record collection must agree on row
count and available columns. This is shape consistency, not a signature or
cryptographic CSV-to-JSON binding; legacy CSV-only output remains readable.

This is not a malware or authenticity claim. Legacy XLS receives only file-size and OLE-signature checks. FI-005 evidence/review CSV and FI-006/FI-007 generated report/Studio artifacts use the bounded generated-artifact profile; FI-014 review-state JSON uses the narrower `review-state-json-ingress-v1` profile while retaining valid legacy entry coercion. Database import/restore has its own bounded JSON profiles. FI-012 freezes a bounded selected set, stages the complete pack beside the destination, and preserves/restores the prior pack on handled failure. Existing-output publication also writes a versioned local marker before its two renames. `client-pack-recover` accepts only four closed states after verifying exact sibling basenames, no unknown sibling/reparse point, and bounded previous/staged tree digests. It refuses ambiguity instead of selecting a plausible directory. Replacement remains non-observer-atomic and non-crash-atomic; simulated abrupt loss is not real host/filesystem durability evidence. The marker uses unkeyed SHA-256 for self-consistency and is not authenticated. Manifest hashes and structurally accepted/copied content do not authenticate source or actor, approve disclosure, prove malware absence, or establish redaction completeness. FI-011 structural acceptance does not authenticate a close template or approve its tasks. No production HTTP upload endpoint exists at this baseline; adding one requires a separate authorization, quarantine, storage, malware scanning, and tenant-isolation slice.

The inventory also closes direct stdlib JSON calls through an exact AST allowlist. FI-015 generated report/workflow/synthetic-demo readers and FI-016 local exception explanation use bounded stable readers; each explicitly selects display or exact-text JSON number representation. FI-013 decodes database, event, or Redis values and is not a filesystem-ingress claim. AP/AR idempotency uses canonical integer-token object JSON; audit metadata, PostgreSQL outbox payloads, PostgreSQL reconciliation rule/attributes/lineage/evidence, SQLite matching rules, and every public SQLite export `_json` field use finite bounded object JSON. Redis sessions use a narrower closed 16 KiB/four-field contract requiring a token digest and explicit UTC expiry. The reconciliation attributes profile preserves its 100,000-byte producer limit; its other three profiles and SQLite matching/export profiles use 4 MiB. All enforce explicit node/depth/collection/scalar ceilings. Audit verification and reconciliation rule decoding preserve backend fingerprint compatibility; SQLite matching preserves historical spaced rule text and policy defaults; Redis preserves tenant-key and TTL behavior; public export preserves all format-v1 field shapes and validates every payload before destination creation; corrupt outbox claims roll back before publisher handoff, and corrupt reconciliation/matching/session/export rows fail before downstream use without sentinel replacement. FI-017 parses already-loaded packaged currency-registry text. The only two direct production `json.loads` calls are the central bounded structured parser and the separately governed packaged currency registry; neither opens an operator-selected path directly.

The authoritative inventory is [file-ingestion-inventory.v1.yaml](file-ingestion-inventory.v1.yaml). Its closed schema and AST-backed tests enumerate every direct pandas or standard-library delimited parser call and every direct PyYAML load/parse call. A new direct parser fails the test until it is routed through the central policy or explicitly recorded as a partial boundary with an owner, limitation, risk, and next action.

## Current budgets

| Budget | Limit |
| --- | ---: |
| File bytes | 67,108,864 |
| Data rows | 1,000,000 |
| Columns | 2,048 |
| Cells | 20,000,000 |
| CSV field characters | 128,000 |
| Client-pack selected files | 10,000 |
| Client-pack traversed entries | 20,000 |
| Client-pack aggregate source bytes | 536,870,912 |
| Client-pack generic-text line characters | 1,048,576 |
| XLSX members | 4,096 |
| One uncompressed XLSX member | 134,217,728 bytes |
| Total uncompressed XLSX bytes | 268,435,456 |
| XLSX compression ratio | 1,000:1 |

These are safety ceilings, not performance claims. The parser may reject earlier, and deployment resource limits remain necessary.

## Structured-document budgets

| Budget | Limit |
| --- | ---: |
| File bytes | 8,388,608 |
| Parsed/event nodes | 200,000 |
| Nesting depth | 64 |
| Items in one collection | 100,000 |
| Characters in one scalar | 1,000,000 |
| YAML aliases | 64 |

These ceilings bound repository-visible parser work; they are not a semantic-validity, malware, or performance guarantee.

## Persisted financial idempotency JSON budget

| Budget | Limit |
| --- | ---: |
| UTF-8 bytes | 4,194,304 |
| Parsed/producer nodes | 100,000 |
| Nesting depth | 32 |
| Items in one collection | 25,000 |
| Characters in one scalar | 262,144 |

The v1 recursive schema permits object, array, string, integer, boolean, and null
values. Fractional quantities must be exact strings and monetary values must be
integer minor units. This contract does not authenticate the database producer,
make restored rows trustworthy, or cover the remaining FI-013 fields.

## Business-record budgets

| Budget | Limit |
| --- | ---: |
| File bytes | 67,108,864 |
| Records | 250,000 |
| Fields per record | 512 |
| Cells | 10,000,000 |
| Characters per field/scalar | 128,000 |
| JSON nodes | 2,000,000 |
| JSON nesting depth | 32 |

These are rejection ceilings, not a throughput or supported-scale claim.

## Generated-artifact budgets

| Budget | Limit |
| --- | ---: |
| File bytes | 67,108,864 |
| CSV rows | 250,000 |
| CSV columns | 512 |
| CSV cells | 10,000,000 |
| CSV field characters | 128,000 |
| JSON nodes | 1,000,000 |
| JSON nesting depth | 64 |
| JSON items per collection | 250,000 |
| JSON scalar characters | 1,000,000 |

These limits are parser controls, not authenticity, malware, or performance evidence.
