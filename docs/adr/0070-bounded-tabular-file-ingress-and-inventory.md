# ADR 0070: Bounded tabular file ingress and closed parser inventory

- Status: Accepted
- Date: 2026-07-26
- Decision owners: platform-security, financial-integrity

## Context

Local-first operation does not make operator-selected exports trustworthy. CSV and spreadsheet parsing can consume unbounded memory or CPU, hide extension/content mismatches, traverse malicious archive paths, expand compressed content, activate workbook relationships, and leak sensitive local paths in errors. ReconForge also had direct parser calls outside its canonical reader, so a single helper alone could not prove coverage.

## Decision

1. Introduce versioned policy `tabular-file-ingress-v1` in `reconforge/io/ingress.py` and invoke it before canonical pandas and direct DuckDB parsing.
2. Enforce fixed file, row, column, cell, field, archive-member, uncompressed-size, and compression-ratio ceilings. Reject symlinks, unsafe/mismatched formats, hostile XLSX paths, duplicate members, unsupported compression, DTD/entities, external relationships, formulas, and active/embedded content.
3. Return only stable safe rejection codes at this boundary; the source path and source values are not included in the public exception message.
4. Maintain a closed schema-v1 file-ingestion inventory. Direct pandas and standard-library delimited parser calls are an exact allowlist checked from the Python AST. Partial callers must remain visible with limitations and a next action.
5. Keep legacy XLS compatibility temporarily with only an OLE signature and file-size check. Do not claim equivalent internal inspection, malware freedom, source authenticity, or complete upload safety.

## Consequences

Malformed, active, or over-budget tabular files fail before normal parsing, including direct DuckDB CSV scans. Mapping and the built-in CSV adapter inherit the same boundary. The inventory prevents silent parser-surface growth. There is an extra deterministic preflight pass over CSV/XLSX content, and legacy/generated/JSON/YAML surfaces remain follow-up work under R-018. A future HTTP upload or evidence redistribution flow still requires quarantine, malware scanning, authorization, storage, retention, and tenant tests.

## Rollback

Revert the call sites, policy module, inventory, and tests together. Do not remove only the preflight calls while leaving documentation that implies enforcement. Restore the previous lock metadata only if the `defusedxml` direct dependency and all protected XML parsing are also reverted.
