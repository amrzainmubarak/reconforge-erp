# ADR 0082: Bound generated report ingress with explicit CSV representation

- Status: Accepted
- Date: 2026-07-26
- Decision owners: Platform Security, Financial Integrity
- Related: ADR 0070, ADR 0071, ADR 0081, FI-006, R-018, P0-SEC-009

## Context

FI-006 was labelled bounded even though variance analysis still used a direct
unrestricted pandas CSV read and an unrestricted standard-library JSON read,
and management-pack metrics used another unrestricted JSON read. The variance
CSV path intentionally preserved source strings because inferred binary floats
can change financial policy inputs. The shared FI-007 generated-artifact reader
already enforced resource and ambiguity limits, but its pandas display typing
was not suitable for variance inputs.

## Decision

1. Extend `generated-artifact-ingress-v1` with explicit `display` and
   `exact-text` CSV modes. Record the selected mode in the returned document and
   reject unknown modes before accessing a file.
2. Preserve `display` as the default for Studio compatibility. Route FI-006
   variance CSV through `exact-text`, so leading zeros and decimal lexemes reach
   strict `Decimal` validation without pandas numeric inference.
3. Route variance and management-report JSON through the existing exact-lexeme,
   duplicate-safe, bounded reader. Preserve each caller's historical fail-closed
   behavior: rejected optional artifacts contribute no metric rather than
   exposing parser details.
4. Keep the existing 64 MiB/file and CSV row/column/cell/field plus JSON
   node/depth/collection/scalar ceilings, regular non-reparse checks, and stable
   pre/post-parse SHA-256 bracket. Do not describe the unkeyed digest as producer
   authentication.

## Compatibility and consequences

- Studio retains its current display inference and CSV-only compatibility.
- Valid variance CSV/JSON continues to load, with stronger exact-text behavior
  for values such as `0002.500001` and exact fractional JSON lexemes.
- Duplicate headers/keys, non-finite JSON, invalid encoding, malformed shapes,
  file changes, reparses, and resource excess fail closed at all FI-006 parser
  entrypoints.
- FI-006 parser coverage is bounded. Producer schema/version binding,
  cryptographic authenticity, actor/disclosure authorization, classification,
  malware quarantine, legacy XLS internals, future uploads/connectors, and
  supported throughput remain open under R-018.

## Rollback

Revert FI-006 routing and the explicit CSV mode. No database or artifact
migration is required. Rollback restores direct unbounded parsing and pandas
numeric inference for variance policy inputs and must be recorded as a security
and financial-integrity regression.
