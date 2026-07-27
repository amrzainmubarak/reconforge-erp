# ADR 0060: Version Client-Pack Redaction Ingress and Manifest

- Status: Accepted
- Date: 2026-07-25
- Scope: local client-pack amount redaction, JSON decimal ingress, current manifest integrity, and historical compatibility

## Context

Client-pack CSV redaction already received amount text, but JSON parsing used the
standard binary floating-point decoder before amount bucketing. A source token
immediately below a bucket boundary could therefore move into the next bucket.
The redaction traversal also applied amount bucketing twice, turning a valid
bucket such as `0-99` into the generic invalid-value token.

The historical `files_manifest.json` was unversioned. Output hashes were
optional, source bytes and the selected financial-input/redaction policies were
absent, and the local source path was copied into a sharing-oriented artifact.
Direct Python behavior and historical manifests remain compatibility surfaces.

## Decision

1. Give client-pack generation and amount bucketing an explicit named
   financial-input policy. Direct Python generation defaults to
   `legacy-financial-input-v1` and the historical manifest. Current CLI/demo
   generation selects `strict-financial-input-v2`.
2. Under strict v2, decode JSON decimal and non-standard numeric constants as
   their source text before redaction. Amount-like keys are parsed and bucketed
   exactly; invalid/scientific/non-finite values receive the full-redaction
   token. Other JSON decimal numerals are serialized as strings in a redacted
   copy so the process does not silently replace their source value with a
   binary approximation. CSV remains exact through `csv.DictReader` text.
3. Apply JSON redaction once per scalar. Preserve the existing bucket limits
   `0`, `100`, `1000`, `10000`, and `100000` and record them as
   `client-pack-redaction-v2` policy.
4. Preserve the unversioned v1 manifest for explicit legacy direct calls,
   including its optional checksum behavior. Current strict output advances to
   schema v2 and always records sorted SHA-256/byte fingerprints of each selected
   source file and every included output file, regardless of the retained CLI
   compatibility flag.
5. Recheck selected source bytes after copying and fail before writing the
   manifest if they changed. Add a path-independent `content_digest` over
   policies, settings, relative input/output fingerprints, and outcomes. Add an
   `artifact_digest` over the complete manifest including `generated_at`.
6. Omit the operator's local source path from the current handoff summary and
   v2 manifest. Historical v1 keeps its existing path field. Relative file names
   remain necessary for verification and may themselves be sensitive.
7. Provide a reader that labels unversioned v1 `legacy-unverified` and verifies
   v2. Optional source/output directory arguments rehash the currently selected
   source set and complete output set; unsafe, duplicate, unsorted, missing, or
   unexpected paths fail closed.
8. Keep the existing warning that redaction is best-effort and requires human
   review. Digests are not signatures, disclosure approvals, audit opinions,
   compliance certifications, or proof of source-system authenticity.

## Consequences

- Strict JSON amount `99.999999999999999999` remains below `100` and receives
  `0-99`; explicit legacy decoding retains the historical float-rounded
  `100-999` result and warning.
- Current v2 manifests can detect manifest, selected-source, included-output,
  path-traversal, and unexpected-output changes. Equivalent relocated source
  content produces the same content digest.
- V2 hashes are always present, so `--include-manifest-checksums` is now a
  compatibility request flag on current CLI output. Explicit legacy direct
  callers retain its historical optional effect.
- Decimal JSON scalars outside amount-like keys become strings only when a
  strict redacted JSON copy is produced. Unredacted files remain byte-for-byte
  copies. Consumers of redacted JSON must treat it as a sharing artifact rather
  than a type-preserving API payload.
- Source paths are omitted, but copied content, relative names, evidence, and
  identifiers may still disclose sensitive information. Human review remains
  mandatory before sharing.

## Rollback

Retain the v1 reader/writer and explicit legacy policy throughout the
compatibility window. Do not route current CLI/demo generation through an
implicit default, restore binary JSON inference, remove required v2 source/
output fingerprints, reveal local paths, or describe digests as sharing
approval. Any future writer must version its schema/algorithm and preserve v1/v2
reading and verification with a documented rollback path.
