# ADR 0092: Bind every public SQLite export JSON field before publication

- Status: Accepted
- Date: 2026-07-27
- Decision owners: Platform Architecture, Data Engineering, Security, Financial Controls
- Scope: FI-013 SQLite public database export and its legacy-summary/matching-lineage producers

## Context

The public SQLite bridge exported five columns whose names end in `_json`.
Audit metadata already had a bounded field contract, while legacy summaries and
matching rules passed through one unrestricted `json.loads` call that replaced
malformed values with a plausible `{"invalid_json": true}` sentinel. Match
result lineage was exported as its historical JSON string without validation.
The destination directory was created before row preflight. Consequently a
corrupt internal row could be hidden or the filesystem could be mutated before
the export was known to be valid.

## Decision

- Maintain an exact `(table, column)` registry for every `_json` column reachable
  through `SELECT_QUERIES`. A contract test compares the registry with the
  migrated SQLite schema so a new exported JSON field cannot bypass review.
- Reuse `audit-metadata-json-v1` for `audit_events.metadata_json` and
  `sqlite-matching-rule-json-v1` for both matching-rule columns.
- Add `sqlite-legacy-import-summary-json-v1` and
  `sqlite-matching-lineage-json-v1`. Each requires a finite, unique-key object
  under 4 MiB, 100,000 nodes, depth 32, 25,000 items per collection, and
  262,144 characters per scalar.
- Route legacy-summary and SQLite matching-lineage producers through the same
  field contracts. Preserve their established compact encodings: ASCII for
  summaries and UTF-8 for lineage.
- Materialize and validate all public payloads before resolving/creating the
  output directory or writing a file. Non-text, malformed, ambiguous,
  non-finite, non-object, or over-budget values fail closed; no sentinel is
  emitted and no `db_exported` event is appended.
- Preserve public format version 1 and valid output shapes. Audit `metadata`,
  legacy `summary`, and both `rule` fields remain decoded objects.
  `match_results.lineage_json` intentionally remains its historical string
  field after validation to avoid an unversioned schema change.
- Remove the exporter from the direct JSON AST allowlist. The central bounded
  parser is the only runtime parser used by these profiles.

## Consequences

All currently exported SQLite JSON columns now have field-specific structural
budgets and corrupt rows are refused before any output publication. This is
structural integrity evidence, not authentication of stored rows, source
provenance, disclosure approval, malware scanning, semantic correctness of
arbitrary nested fields, supported scale, or production readiness.

The production direct-parser inventory now contains only the central bounded
structured-document parser and the separately governed packaged currency
registry parser. FI-013 remains partial because authenticity, authorization,
live-service, and throughput controls remain open under R-018.

## Compatibility and migration

No database migration, CLI option, filename, export format version, or valid
field shape changes. Existing valid finite object rows inside the declared
budgets remain readable. Previously accepted corrupt/non-object/non-text or
over-budget state now fails visibly. The lineage string is validated but not
renamed or decoded in the public document.

## Rollback

Revert the two profiles/schemas, producer routing, exact export registry,
pre-publication ordering, tests, inventory, and governance as one unit. No
stored row is rewritten by this slice. Do not restore the former sentinel
behavior in isolation because it makes corruption appear to be ordinary data.
