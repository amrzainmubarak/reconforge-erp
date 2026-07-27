# ADR 0081: Bound Studio generated-artifact ingress

- Status: Accepted
- Date: 2026-07-26
- Decision owners: Platform Security, Product Experience
- Related: ADR 0070, ADR 0071, ADR 0080, FI-007, R-018, P0-SEC-009

## Context

Current local Studio read generated and operator-selected CSV/JSON through four
direct pandas calls and one unrestricted JSON helper. Missing or malformed
helper inputs became an empty view, but direct route reads could raise a server
error. None shared byte/row/cell/depth limits, duplicate-header/key rejection,
reparse refusal, or source-change detection. Replacing pandas display inference
would change current Studio output, while requiring a companion manifest would
break historical CSV-only output.

## Decision

1. Introduce `generated-artifact-ingress-v1` with 64 MiB/file, 250,000 CSV
   rows, 512 columns, 10,000,000 cells, and 128,000 characters/CSV field. JSON
   permits 1,000,000 nodes, depth 64, 250,000 items/collection, and 1,000,000
   characters/scalar.
2. Require regular non-reparse files and stable bounded SHA-256 plus byte count
   before and after parsing. Reject empty, changed, malformed, duplicate-header,
   duplicate-key, non-finite, invalid-encoding, and over-budget artifacts with
   code-only internal errors.
3. Keep pandas `keep_default_na=False` and its historical display typing after
   tabular preflight. Preserve JSON fractional/exponent lexemes as exact text.
4. Route the health, rule-results, variance, control-matrix, control-pack, and
   evidence-coverage reads through the central helpers. Missing or rejected
   artifacts retain the existing empty-state behavior rather than exposing a
   path, value, parser exception, or traceback.
5. When a companion JSON file exists, require its named collection to be an
   object-record list with the same row count and columns present in the CSV.
   Keep CSV-only output readable. Do not call this a cryptographic binding:
   current producer JSON does not digest the CSV bytes.

## Compatibility and consequences

- Existing valid CSV-only artifacts and Studio display typing remain supported.
- Existing valid companion JSON must now agree on record count and field shape;
  malformed or inconsistent companions make the view empty and visible as not
  generated rather than silently displaying unrelated CSV.
- Stable local hashes prove self-consistency only. They do not authenticate the
  producer, authorize processing/disclosure, classify fields, scan malware, or
  prove supported throughput or production safety.
- FI-007 parser coverage becomes bounded, while FI-006/other generated-report,
  legacy XLS, upload, connector, authenticity, and operational controls remain.

## Rollback

Revert the Studio routing and remove the helper/test. No database or artifact
migration is required. Rollback restores unbounded parsing, direct-route
tracebacks, ambiguity, resource-exhaustion, and file-race risks and must be
recorded against R-018 rather than described as equivalent safety.
