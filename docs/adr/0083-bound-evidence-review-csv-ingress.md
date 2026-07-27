# ADR 0083: Bound evidence and review CSV ingress to parsed-byte provenance

- Status: Accepted
- Date: 2026-07-26
- Decision owners: Evidence Security, Financial Integrity
- Related: ADR 0061, ADR 0070, ADR 0081, ADR 0082, FI-005, R-018, P0-SEC-009

## Context

FI-005 evidence and review assembly retained two direct unrestricted pandas CSV
readers. Strict financial mode required exact source text, while the public
legacy mode intentionally retained pandas display inference. Evidence case
construction also re-read match and rule-result CSV files for every exception,
creating avoidable input-dependent repeated work. Evidence-index v3 fingerprint
generation hashed paths separately from parsing, so a race between parse and
initial fingerprint could describe bytes different from those used for cases.

## Decision

1. Route both FI-005 readers through `generated-artifact-ingress-v1`. Select
   `exact-text` for strict financial policy and `display` for the named legacy
   compatibility policy.
2. Missing optional CSV remains an empty frame. An existing malformed,
   ambiguous, changed, reparse, invalid-encoding, or over-budget CSV fails closed
   with a code-only `GeneratedArtifactError`; it is never hidden as “no
   exceptions”. CLI evidence/review surfaces translate this to one generic,
   path-free message.
3. Cache selected evidence CSV documents by path for one binder operation.
   Parse each selected exception/match/rule file at most once, then reuse its
   immutable dataframe and parsed-byte checksum/size.
4. Build evidence-index v3 CSV fingerprints from the cached documents, freeze
   the selected path list, and verify every cached document still names the same
   bytes before publishing the index. Continue the existing bounded fingerprint
   handling for non-CSV selected inputs.
5. Keep the shared 64 MiB/file, 250,000-row, 512-column, 10,000,000-cell, and
   128,000-character-field ceilings. Do not call unkeyed SHA-256 producer
   authentication or schema authorization.

## Compatibility and consequences

- Valid strict and legacy evidence/review outputs remain readable with their
  existing financial behavior and output schemas.
- An invalid present artifact now stops evidence/review generation instead of
  allowing parser-specific errors or an incomplete evidence set.
- Binder CSV parsing is linear in the selected files rather than repeated per
  exception. This is a structural bound, not a supported-throughput benchmark.
- FI-005 CSV parser coverage becomes bounded. Review-state JSON, producer/schema
  authentication, disclosure authorization, classification, malware quarantine,
  legacy XLS, uploads/connectors, and operational scale remain open under R-018.

## Rollback

Revert the two consumers, cache/provenance use, and CLI translation. No database
or artifact migration is required. Rollback restores unrestricted parsing,
repeated per-case reads, and possible parsed-byte/fingerprint divergence and
must be recorded as a security and evidence-integrity regression.
