# ADR 0128: Bounded browser-local Mapping Studio preview

- Status: Accepted
- Date: 2026-07-28

## Context

P2-005 requires a usable source preview and canonical column-mapping flow that
does not hide missing or malformed financial values. Uploading preview data to a
server, parsing unbounded files, or coercing invalid amounts would conflict with
the local-first and financial-correctness boundaries.

## Decision

The Mapping Studio foundation parses CSV/TSV inside the browser only. It accepts
at most 256 KiB, 100 columns, and 200 preview rows, rejects null bytes, duplicate
or blank headers, unclosed quoted fields, unsupported file types, duplicate
source mappings, malformed exact-decimal text, invalid ISO currency codes, and
impossible calendar dates. Missing values stay as empty text and render as
data-quality issues; they are never converted to zero. Four required canonical
fields must be mapped explicitly through labelled native select controls.

The foundation does not persist, approve, execute, or upload a mapping. A later
versioned mapping contract must add draft identity, authorization, provenance,
approval, and server-side replay before publication is possible.

## Consequences

- Keyboard-native controls, English/Arabic text, RTL layout, visible load/error/
  truncation states, and browser E2E coverage are available now.
- The preview parser is deliberately bounded and is not a general CSV ingestion
  engine, malware scanner, source authenticator, or proof of semantic validity.
- Rollback is additive: remove the route/component/parser and restore the prior
  navigation item; no data migration exists.
