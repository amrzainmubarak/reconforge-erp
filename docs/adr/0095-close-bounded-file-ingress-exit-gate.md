# ADR 0095: Close the bounded file-ingress abuse exit gate without expanding its claim

- Status: Accepted
- Date: 2026-07-27
- Scope: P0-SEC-009 evidence-defined exit gate

## Context

P0-SEC-009 requires safe refusal of size, type, path, decompression, formula,
XML, and YAML abuse without sensitive error disclosure. The repository now has
direct hostile cases for those dimensions, closed runtime-policy parity, and
exact AST inventories for tabular, JSON, and YAML parser calls. Later slices
also bounded every current direct filesystem JSON reader and every direct
persisted JSON decoder.

The broader inventory deliberately retains partial surfaces and residual risk
for legacy XLS internals, source and actor authenticity, disclosure approval,
malware scanning or quarantine, real host-loss durability, future uploads and
connectors, and declared-throughput evidence. None of those controls appears in
the task's recorded exit evidence, and treating them as implicit requirements
would make the Phase 0 gate unbounded while obscuring the residual risks.

## Decision

Close P0-SEC-009 only for its exact repository-visible abuse contract:

- fixed size and structural budgets;
- regular-file, reparse, type, signature, and extension checks;
- archive traversal, duplicate, encryption, compression, and decompression
  limits for protected XLSX paths;
- XML DTD/entity/external relationship, active-content, and formula refusal;
- duplicate, non-finite, cyclic, merge, alias, depth, collection, encoding, and
  unsafe-tag refusal for bounded JSON/YAML paths; and
- stable public error codes/messages that exclude the local path and rejected
  source value in the tested boundary.

Keep FI-012 and FI-013 partial and keep R-018 open. Do not describe the result
as malware-free, authenticated evidence, safe redistribution, secure upload,
complete legacy-XLS inspection, or deployed protection.

## Consequences

The Phase 0 backlog reflects a finite, reproducible exit gate. Existing valid
file compatibility is unchanged because this decision changes governance
status only. Any upload, connector, stricter legacy-XLS policy, malware
provider, signature/provenance mechanism, or disclosure workflow requires a
separate implementation decision and new evidence.

## Rollback

Reopen P0-SEC-009 if a current direct parser escapes the exact inventories, a
listed hostile case stops failing safely, or the task exit evidence is formally
expanded. Do not remove the residual risks merely because the bounded gate is
closed.
