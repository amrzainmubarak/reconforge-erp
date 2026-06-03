# Evidence Integrity Manifests

ReconForge evidence binders and client packs can include SHA-256 checksums to support local integrity review.

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

## Client Pack Manifest

Client packs always write:

```text
output/client_pack/files_manifest.json
```

When `--include-manifest-checksums` is used, included client-pack files receive SHA-256 hashes.

## What This Proves

Checksums help detect whether a generated file changed after the manifest was created.

## What This Does Not Prove

- This is not a legal digital signature.
- This does not certify the accuracy of source data.
- This does not replace audit judgment.
- This does not prove that evidence was accepted by a client, auditor, regulator, or court.
