# ADR 0073: Bound generated manifest JSON readers without changing redaction semantics

- Status: Accepted
- Date: 2026-07-26
- Decision owners: evidence-security, platform-security

## Context

Client-pack manifests and evidence indexes are generated-local JSON artifacts with versioned schema, policy, fingerprint, and digest verification after parsing. Their readers used direct `read_text` plus `json.loads`, so duplicate keys, non-finite constants, excessive size, and deep or wide structures could reach verification first. The same FI-012 surface also contains JSON/CSV redaction and text-copy compatibility paths. Strict JSON redaction intentionally preserves decimal lexemes with a custom `parse_float` hook before bucketing; replacing that path with the general structured reader would silently change financial redaction behavior.

## Decision

1. Route only `read_client_pack_manifest` and `read_evidence_index` through `read_json_document` in this slice. Preserve their stable public invalid-JSON messages while chaining the structured rejection internally.
2. Preserve current client-pack schema v2 and legacy unversioned v1 behavior, current evidence-index schema v3 and legacy v2 behavior, fingerprint checks, digest verification, and verification-status labels.
3. Add dedicated duplicate-key, non-finite, depth, malformed, default-size-ceiling, safe-message, and structured-cause cases for both readers, and retain the existing current/legacy/digest/tamper contracts.
4. Keep FI-012 `partial`: set policy coverage to partial, not complete, because `_redact_json_file`, `_redact_csv_file`, text copying, artifact provenance, and malware/quarantine state remain outside one uniform bounded redistribution policy.
5. Do not weaken strict decimal-lexeme redaction or call a local hash a signature, source authentication, malware result, disclosure approval, or audit opinion.

## Consequences

The two versioned manifest readers now reject ambiguous and over-budget JSON before semantic or digest verification. Valid current and legacy artifacts remain compatible. Unsupported suffixes, symlinks, invalid UTF-8, and read races inherit the central rejection boundary. FI-012 as a whole remains partial, and generated artifact redistribution remains a high-residual-risk workflow requiring separate bounded lexeme-preserving readers, classification, provenance, scanning, authorization, and retention controls.

## Rollback

Revert both reader migrations, their imports, dedicated tests, FI-012 partial-coverage wording, module/security evidence, and governance records together. Do not describe either reader as bounded after restoring direct parsing. If financial JSON redaction is migrated later, design and test an explicit lexeme-preserving bounded parser rather than reusing a float-producing reader or weakening existing redaction fixtures.
