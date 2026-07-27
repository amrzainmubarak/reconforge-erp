# ADR 0085: Close the direct filesystem JSON parser inventory

- Status: Accepted
- Date: 2026-07-26
- Decision owners: Platform Security, Financial Integrity
- Related: ADR 0058, ADR 0059, ADR 0071, ADR 0082, ADR 0084, FI-013, FI-015, FI-016, FI-017, R-018, P0-SEC-009

## Context

The file-ingestion inventory enforced exact direct tabular and PyYAML parser
calls but did not enforce direct `json.load`/`json.loads` calls. Repository audit
found 20 production calls: six opened filesystem JSON directly, 12 decoded
database/Redis/event values, one was the bounded central JSON parser, and one
parsed already-loaded packaged currency-registry text. The six filesystem calls
covered user-selected exception explanations, generated dashboard/demo files,
period comparisons, rule results, and the synthetic Studio bridge. They had
different root-shape and numeric-representation compatibility requirements.

## Decision

1. Add `direct_json_parser_allowlist` to the closed schema-v1 inventory and an
   exact AST equality test. Every remaining direct stdlib JSON call must name a
   surface, count, and rationale.
2. Add a stable `GeneratedJsonValueDocument` reader for object or list roots.
   Retain the object-only wrapper for existing callers. Both require bounded
   strict UTF-8, unique keys, finite values, regular non-reparse files, and equal
   SHA-256/size before and after parse.
3. Record explicit JSON numeric representation: `exact-text` preserves
   fractional/exponent lexemes and remains the default; `display` retains
   historical stdlib float/int construction. Invalid modes fail before file
   access.
4. Route the six direct filesystem calls through the shared reader. FI-015
   generated report/workflow/demo readers explicitly select `display` so current
   period/rule digests and Studio numeric contracts do not change. FI-016
   exception explanation uses a narrower 16 MiB/500,000-node/depth-32 profile,
   preserves list/envelope/object selection, and emits path-free failures.
5. Expand excluded FI-013 to enumerate all 12 database/Redis/event decoders.
   Add excluded FI-017 for already-loaded packaged currency-registry text. Do
   not misrepresent either category as operator-selected filesystem ingress.

## Compatibility and consequences

- Historical valid period/rule artifacts retain their verification status and
  exact current digests; Studio/demo numeric values remain numbers. Existing
  exact-text financial report readers remain unchanged.
- Duplicate, non-finite, invalid-encoding, reparse, changed, malformed, wrong
  root-shape, or over-budget files now fail before downstream interpretation.
- The exception explanation CLI no longer prints a selected path or JSON parser
  excerpt on structural failure.
- Each accepted file is hashed twice. This is linear bounded I/O and no supported
  throughput claim; authenticated producer/schema manifests remain absent.
- Direct persisted-value decoders are now visible but their database column,
  Redis value, and event size/schema contracts remain separate work.

## Rollback

Revert the value-document/mode extension, six call-site migrations, JSON AST
allowlist/schema entries, tests, and governance updates. No stored artifact or
database migration is required. Rollback restores unrestricted filesystem reads
and an unenforced direct JSON parser surface and must be recorded as a security,
compatibility-evidence, and safe-error regression.
