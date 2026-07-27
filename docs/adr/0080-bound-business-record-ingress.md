# ADR 0080: Bound exact business-record ingress

- Status: Accepted
- Date: 2026-07-26
- Decision owners: Platform Security, Financial Integrity
- Related: ADR 0070, ADR 0071, FI-008, R-018, P0-SEC-009

## Context

The shared platform CSV/JSON reader and the ledger, inventory, and receivables
CLI JSON readers parsed complete local files without one common byte, record,
cell, depth, or ambiguity policy. Generic JSON silently discarded non-object
records, selected the first truthy envelope alias, and constructed fractional
numbers as binary floats. Four import services recalculated the source checksum
after parsing, so a changed path could produce evidence for bytes other than
the imported object. Matching used the same generic reader but was absent from
the FI-008 module inventory.

## Decision

1. Introduce `business-record-ingress-v1` as the sole internal FI-008 CSV/JSON
   boundary: 64 MiB per file, 250,000 records, 512 fields per record, 10,000,000
   cells, and 128,000 characters per field/scalar. JSON additionally allows at
   most 2,000,000 nodes and depth 32.
2. Require regular non-reparse paths and compare bounded SHA-256 plus byte count
   before and after parsing. Return those parsed-byte values with the records
   and policy profile.
3. Use duplicate-safe, non-finite-rejecting strict UTF-8 JSON and preserve every
   fractional/exponent lexeme as text before domain-specific Decimal parsing.
   Accept a direct list, exactly one recognized list envelope, or the historical
   generic single-record object; reject alias ambiguity and every non-object
   list member instead of dropping it.
4. Run strict CSV parsing only after `tabular-file-ingress-v1` preflight; reject
   blank/duplicate headers and row-count instability while preserving cell text.
5. Migrate account, control, intercompany, journal, and matching consumers plus
   specialized ledger, inventory, and receivables CLI readers. Retain
   `read_local_records` as a compatibility shim over the bounded document.
6. Reuse the parsed-byte digest, size, and profile in account/control/
   intercompany/journal audit and outbox evidence; never recompute provenance
   from a later file state.

## Compatibility and consequences

- Valid CSV, direct-list JSON, single-envelope JSON, and generic single-object
  JSON remain readable. Existing specialized CLI allowed-field and public error
  contracts remain in place.
- JSON fractional values now reach financial/quantity domain parsers as exact
  source text instead of binary floats. Strict matching therefore accepts an
  exact JSON numeric lexeme that the old float-producing reader rejected; the
  persisted strict-policy marker and deterministic match contract remain.
  Duplicate keys, NaN/Infinity, ambiguous
  aliases, non-object rows, invalid UTF-8, resource excess, reparse paths, and
  changes during parsing fail visibly.
- Domain schemas remain owned by each service. This boundary does not validate
  business meaning, authenticate source/author, authorize imports centrally,
  classify arbitrary free text, scan malware, or establish performance scale.
- FI-008 parser coverage is bounded. R-018 remains partially mitigated because
  other Studio/report/legacy-XLS/upload/connector surfaces remain incomplete.

## Rollback

Revert the consumer routing and remove the central reader/test while leaving
databases unchanged; the added audit/outbox metadata is additive JSON. Such a
rollback reopens binary-float, ambiguity, resource-exhaustion, silent-record-
drop, race, and provenance mismatch risks and must be recorded against R-018.
