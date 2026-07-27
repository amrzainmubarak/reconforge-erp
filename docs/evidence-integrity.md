# Evidence Integrity Manifests

ReconForge evidence binders include SHA-256 checksums, and current client-pack
CLI manifests require source/output SHA-256 fingerprints, to support local
integrity review.

## Evidence Binder Manifest

Evidence binder generation writes:

```text
output/evidence/evidence_manifest.json
```

The manifest includes:

- `generated_at`
- ReconForge tool version
- source output folder
- evidence output folder
- privacy note
- integrity model statement
- file path, size, and SHA-256 hash for generated evidence files

The manifest excludes itself from the hash list to avoid self-reference ambiguity.

Current CLI/demo `evidence_index.json` uses schema v3. It declares strict
financial-input policy and risk-score policy `integer-0-to-100-v1`, fingerprints
the selected exception/match/rule/review inputs, and records a path-independent
case-decision content digest plus a complete index artifact digest. Source files
are rechecked before the index is written, and the current reader can optionally
rehash the recognized local input set. Historical direct Python generation
retains schema v2 and reads as `legacy-unverified`.

Valid scores remain integers from 0 through 100. Missing or invalid values are
emitted as `null` with an explicit `risk_score_status`, and generated human-
readable files show them as unavailable rather than zero. Strict CSV reads keep
the source lexeme, so fractional or malformed explicit scores become visible
data-quality evidence cases rather than being rounded by type inference.

## Client Pack Manifest

Client packs always write:

```text
output/client_pack/files_manifest.json
```

Current CLI/demo manifests use schema v2 and always include SHA-256/byte
fingerprints for selected source files and included output files. They also
record strict financial/redaction policy, a path-independent content digest,
and a complete manifest artifact digest. The retained
`--include-manifest-checksums` option is a compatibility request flag; explicit
legacy direct calls keep the historical optional-checksum manifest.

V2 can be rechecked against the local source and output directories. Historical
unversioned manifests remain readable as `legacy-unverified`; missing policy or
source provenance is not manufactured.

## What This Proves

Checksums help detect whether a generated file changed after the manifest was created.

Current evidence-index digests also bind the selected local input fingerprints,
policies, and case decisions. Equivalent recognized inputs can reproduce the
content digest independently of their local folder or generation timestamp.

## What This Does Not Prove

- This is not a legal digital signature.
- This does not certify the accuracy of source data.
- This does not replace audit judgment.
- This does not prove that evidence was accepted by a client, auditor, regulator, or court.
- Client-pack checksums do not prove that best-effort redaction removed every
  sensitive value or authorize disclosure.
- Evidence-index hashes do not authenticate upstream exports, stabilize the
  report-local sequential case IDs, prove evidence completeness, or approve a
  financial/control decision.
