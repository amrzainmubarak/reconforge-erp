# ADR 0075: Bound and stream client-pack CSV redaction

- Status: Accepted
- Date: 2026-07-26
- Decision owners: financial-integrity, evidence-security, platform-security

## Context

FI-012 CSV redaction used `csv.DictReader`, accumulated every row in memory, accepted replacement-decoded/fallback behavior indirectly, and wrote the final target directly. It had no shared file, row, column, cell, field, content-type, or shape ceiling. Client-pack destination preparation is destructive, so predictable hostile CSV must fail before fingerprint hashing or destination mutation. CSV monetary fields already arrive as exact text in both strict and legacy modes; changing them through dataframe or float inference would regress bucket semantics.

## Decision

1. Reuse `tabular-file-ingress-v1` for every selected CSV redaction input before fingerprint hashing and destination preparation, and repeat validation immediately before the redaction read.
2. Add a bounded duplicate-header check using the inventoried `csv.DictReader` family. Record both direct call sites in the exact AST allowlist: header preflight and streaming redaction.
3. Read strict UTF-8 CSV with strict CSV syntax and preserve field strings exactly. Apply the existing name and amount transformations row by row; do not construct a dataframe, infer numeric types, or accumulate all rows.
4. Write each transformed row to a hidden temporary file in the target directory, close it, then replace the target. Remove the temporary file on failure. This gives atomic publication for one CSV file, not for the complete client pack.
5. Treat empty, malformed-shape, invalid-UTF-8, duplicate-header, type-mismatched, oversized-field, and default-ceiling oversized CSV as invalid. Preserve one generic public error with a code-only `FileIngressError` cause.
6. Keep FI-012 `partial`: text redaction/copying, non-redacted artifact copying, pack-wide transactionality under concurrent source mutation, classification, authenticated provenance, disclosure authorization, malware scanning/quarantine, and retention enforcement remain open.

## Consequences

Valid CSV redaction retains exact field text and strict/legacy amount buckets while using bounded memory proportional to one row plus parser buffers. Predictable hostile CSV cannot trigger source fingerprint hashing or clear an existing destination. A source can still change between preflight and copy; repeated validation, header/shape checks, temporary-file cleanup, and the final source fingerprint detect or contain that case, but other files already published in the pack are not rolled back. This work proves neither redaction completeness nor safe redistribution.

## Rollback

Revert the streaming writer, repeated preflight, duplicate-header rejection, allowlist count, dedicated tests, FI-012 evidence, and governance records together. Do not restore row accumulation or malformed/empty text fallback as a compatibility safety path. Any successor ceilings or parser semantics require a versioned policy and retained exact-field fixtures.
