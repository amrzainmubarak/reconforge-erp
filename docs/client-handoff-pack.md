# Client Handoff Pack

The client handoff pack is a local folder for consultants, internal audit teams, and controllers who need to share ReconForge outputs inside an engagement or close process.

## Command

```bash
reconforge report client-pack --input output/demo --output output/demo_client_pack
```

Redacted handoff example:

```bash
reconforge report client-pack --input output/demo --output output/client_pack_redacted --redact-names --redact-amounts --exclude-raw-records --include-manifest-checksums
```

Summary-only example:

```bash
reconforge report client-pack --input output/demo --output output/client_pack_summary --summary-only
```

## Included Files

When available, the command copies:

- `executive_report.html`
- `management_pack.xlsx`
- `review_register.xlsx`
- `dashboard.html`
- `source_summary.md` when the source output contains `summary.md`
- `evidence/index.html`
- `evidence/evidence_register.xlsx`
- `evidence/evidence_index.json`
- `evidence/evidence_manifest.json`
- generated evidence case files under `evidence/`

It also writes:

- `handoff_summary.md`
- `next_steps.md`
- `data_privacy_note.md`
- `files_manifest.json`

Missing optional files and excluded files are listed in the summary and manifest. Hidden files and system folders are not included.

Current CLI/demo generation writes schema-v2 `files_manifest.json` under
`strict-financial-input-v2`. It includes the exact redaction/bucket policy,
sorted SHA-256/byte fingerprints for every selected source and included output,
a path-independent content digest, and a complete artifact digest. The local
source-folder path is omitted. Direct Python calls retain the historical
unversioned manifest by default and readers label it `legacy-unverified`.

## Redaction and Sharing Controls

Available options:

- `--redact-names`
- `--redact-amounts`
- `--exclude-raw-records`
- `--summary-only`
- `--exclude-evidence`
- `--include-manifest-checksums`

Redaction is applied only to files copied into the client pack. The source output folder is not modified. Binary workbooks are excluded when redaction is requested because text-level redaction cannot safely rewrite every workbook cell.

The destination cannot equal or contain the source and cannot be placed below
the source `evidence/` tree. The historical `source/client_pack` demo location
remains supported because top-level non-evidence subdirectories are excluded
from the frozen candidate set. Selection is limited to 10,000 regular
non-symlink files and 512 MiB aggregate, with 64 MiB per file and 20,000
traversed entries. Generic redacted text must be strict UTF-8 and is processed
one line at a time with a 1 MiB line ceiling. Non-redacted content is copied in
bounded chunks and checked for changes.

ReconForge builds the complete pack in a sibling staging directory and checks
the selected source fingerprints again before publication. A handled failure
leaves the prior pack unchanged or restores it. Fresh publication uses one
same-filesystem rename; replacing an existing non-empty directory on Windows
uses a rollback rename followed by the publish rename, so it is not
observer-atomic or crash-atomic. Before the first replacement rename,
ReconForge writes a versioned local transaction marker that binds the exact
staging/rollback names and bounded SHA-256 tree digests.

If a process or host stops during that narrow replacement window, do not rename
or delete the hidden siblings manually. Run:

```text
reconforge report client-pack-recover --output output/client_pack
```

Recovery is explicit and fail-closed. It accepts one valid marker and one of
four documented old/staged/rollback states; it refuses unexpected siblings,
multiple or tampered markers, changed tree bytes, reparse points, and ambiguous
states before mutation. The returned action is one of
`aborted-before-swap`, `restored-previous`, `finalized-published`, or
`confirmed-published`. Re-run the command only after investigating any refusal;
never delete an unknown sibling merely to make the command pass.

The marker and tree hashes are integrity/self-consistency aids, not
authentication, a signature, source provenance, disclosure approval, or actor
authorization. File `fsync` does not guarantee parent-directory durability on
every filesystem or host-loss mode, and the two-rename publication is still not
observer-atomic or crash-atomic.

Strict redacted JSON preserves decimal source lexemes before deciding amount
buckets. Decimal JSON numerals outside amount-like keys are emitted as strings
in the redacted copy rather than silently passing through binary floating point;
unredacted files remain byte-for-byte copies. Treat redacted JSON as a sharing
artifact, not a type-preserving API contract.

## Recommended Use

1. Run the demo or management-pack workflow.
2. Update review statuses in Studio or with the CLI.
3. Export the review register.
4. Generate evidence binder outputs.
5. Create the client pack.
6. Review the privacy note before sharing the folder outside the company or engagement team.

## Local-First Limitation

The pack is a file-based handoff folder. It does not add authentication, a database, approvals, malware scanning, disclosure authorization, or cloud storage. Treat it as a structured local output for review meetings, audit preparation, and consultant handover.

Evidence case folders can contain generated source-record extracts. Review the manifest and privacy note before external sharing.

`read_client_pack_manifest` reads historical/current manifests, and
`verify_client_pack_manifest_payload` verifies current v2. Supplying source and
output folders also rechecks their current bytes. These hashes are local
integrity aids, not signatures, source authentication, or permission to share.

See [Redaction controls](redaction-controls.md) and [Evidence integrity](evidence-integrity.md).
