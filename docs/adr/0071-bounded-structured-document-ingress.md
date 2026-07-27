# ADR 0071: Bounded structured-document ingress

- Status: Accepted
- Date: 2026-07-26
- Decision owners: platform-security, financial-integrity

## Context

Safe YAML construction prevents arbitrary Python object creation, but it does not by itself bound bytes, nesting, collection width, scalar size, aliases, or the object graph created by a document. PyYAML also accepts duplicate mapping keys with last-key-wins behavior unless the loader changes. Standard JSON accepts duplicate keys and non-finite constants by default. Configuration, mapping, control-pack, and Reconciliation-as-Code inputs therefore had ambiguity and resource-exhaustion paths even though their domain models validated after parsing.

## Decision

1. Introduce versioned `structured-document-ingress-v1` in `reconforge/io/structured.py` with fixed ceilings of 8,388,608 file bytes, 200,000 nodes, depth 64, 100,000 items in one collection, 1,000,000 characters in one scalar, and 64 YAML aliases.
2. Reject non-regular or symlinked files, unsupported suffixes, invalid UTF-8, changed/oversized reads, JSON duplicate keys and non-finite constants, and malformed or over-budget JSON with stable code-only errors.
3. Preflight YAML events before construction; reject multiple documents, merge keys, excess aliases/nodes/depth/scalars, duplicate mapping keys, cyclic constructed graphs, unsafe tags, unsupported constructed value types, and non-finite legacy values. Preserve strict financial scalar lexemes through the existing named policy.
4. Route configuration, mapping inspection/validation, control-pack loading, and Reconciliation-as-Code YAML through this boundary. Keep valid legacy/strict policy selection intact; malformed configuration details become non-sensitive stable summaries.
5. Extend the closed file-ingestion inventory with exact runtime-policy parity and an AST allowlist for every direct `yaml.parse`, `yaml.safe_load`, or `yaml.load` call. Keep the close-workflow direct reader explicitly partial rather than relabeling it bounded.

## Consequences

Selected YAML control surfaces now fail before domain validation on ambiguous, unsafe, or over-budget documents. JSON has a reusable bounded parser but generated artifacts, restore/import, Studio/report, and close-workflow callers are not migrated by this slice. The limits are denial-of-service safeguards, not proof of semantic correctness, author authenticity, malware absence, or performance. Duplicate-key rejection and generic configuration validation errors intentionally replace silent last-key-wins and source-detail-bearing failures.

## Rollback

Revert the structured reader, unique-loader option, migrated call sites, inventory/schema/AST contracts, module/security evidence, and dedicated tests together. Do not restore direct parsers while retaining bounded wording. If a valid compatibility document exceeds a ceiling, review a versioned policy successor and fixture evidence rather than bypassing the boundary or weakening one call site.
