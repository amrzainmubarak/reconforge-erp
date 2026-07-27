# ADR 0074: Bound client-pack JSON redaction while preserving financial lexemes

- Status: Accepted
- Date: 2026-07-26
- Decision owners: financial-integrity, evidence-security, platform-security

## Context

FI-012 client-pack JSON redaction read each generated artifact without a byte ceiling and parsed it directly. Strict mode deliberately returned fractional JSON tokens as source text so an amount such as `99.999999999999999999` remained below the `100` bucket boundary; legacy mode deliberately retained historical binary-float behavior. Malformed JSON was decoded with replacement and treated as unrestricted text, which could hide structural failure and write a partially trusted copy. The client-pack destination is prepared destructively before copying, so a predictable input rejection should occur before destination preparation whenever possible.

## Decision

1. Extend `structured-document-ingress-v1` JSON APIs with an explicit `preserve_float_lexemes` representation option. It returns fractional and exponent tokens as their exact strings while leaving integer tokens as integers; all existing byte, node, depth, collection, scalar, encoding, regular-file, duplicate-key, and non-finite rejection remains active.
2. Route `_redact_json_file` through that bounded reader. Strict financial mode enables exact float lexemes; legacy mode keeps standard finite-float construction and its documented warning/compatibility behavior.
3. Preflight every selected JSON redaction input before preparing the destination, then read it again under the same policy while copying. Duplicate, non-finite, malformed, deep, invalid-UTF-8, and oversized JSON therefore fails with one code-only public message and a structured internal cause before ordinary destination mutation.
4. Remove malformed-JSON fallback to text redaction. Treating structurally invalid JSON as a different unrestricted format is not a supported compatibility contract.
5. Keep the policy identifier at `structured-document-ingress-v1`: ceilings and rejection rules are unchanged; the new option changes only the representation of otherwise-valid finite fractional tokens.
6. Keep FI-012 `partial`. CSV redaction, CSV/text reads and copying, full output transactionality under concurrent source mutation, classification, authenticated provenance, disclosure authorization, malware scanning/quarantine, and retention enforcement remain open.

## Consequences

Valid strict and legacy JSON redaction preserves existing amount buckets and non-amount output types. Invalid or over-budget JSON no longer produces a best-effort text copy. Preflight prevents deterministic hostile JSON from clearing or creating the requested output directory. The second bounded read protects against a changed input, but a concurrent change after preflight can still fail after destination preparation; the final fingerprint check also detects source mutation, and complete atomic client-pack publication remains a separate slice. This work does not prove redaction completeness, source authenticity, disclosure approval, malware absence, or safe redistribution.

## Rollback

Revert the lexeme option, redaction/preflight migration, dedicated tests, FI-012 evidence, and governance records together. Do not restore malformed-JSON-to-text fallback or describe direct unbounded parsing as compatible safety. If a policy successor changes ceilings or rejection behavior, version it explicitly and retain strict/legacy financial fixtures.
