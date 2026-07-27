# Redaction Controls

ReconForge client packs can be generated with optional sharing controls to reduce accidental disclosure when preparing a handoff folder.

## Command Examples

Summary-only handoff:

```bash
reconforge report client-pack --input output/demo --output output/client_pack --summary-only
```

Redacted handoff with raw evidence extracts excluded:

```bash
reconforge report client-pack --input output/demo --output output/client_pack_redacted --redact-names --redact-amounts --exclude-raw-records --include-manifest-checksums
```

## Available Options

| Option | Behavior |
| --- | --- |
| `--redact-names` | Redacts customer, supplier, employee, reviewer, engineer, and equipment identifiers where practical in copied text/CSV/JSON/HTML files. |
| `--redact-amounts` | Buckets or redacts amount-like values where practical in copied text/CSV/JSON/HTML files. |
| `--exclude-raw-records` | Excludes evidence raw extracts such as `source_records.csv`, `match_candidates.csv`, `audit_trail.json`, and `triggered_rules.yml`. |
| `--summary-only` | Includes generated handoff notes and the source summary if available, while excluding detailed reports and evidence. |
| `--exclude-evidence` | Excludes the evidence folder from the handoff pack. |
| `--include-manifest-checksums` | Compatibility request flag. Current schema-v2 CLI manifests always hash selected inputs and included outputs; explicit legacy direct calls retain optional output hashes. |

## Important Limitations

- Redaction is applied only to copied/generated client-pack files.
- The original `output/` folder is not modified.
- Binary workbooks are excluded when redaction is requested because text-level redaction cannot safely rewrite every workbook cell.
- Redaction is a practical safeguard, not a guarantee that every sensitive value has been removed.
- Current amount bucketing uses strict exact-text input and the recorded
  boundaries `0`, `100`, `1000`, `10000`, and `100000`. Malformed,
  non-finite, or scientific-notation amounts receive the full-redaction token.
- Strict redacted JSON emits non-amount decimal numerals as strings to avoid
  silent binary approximation. Unredacted copies remain byte-identical.
- Selected client-pack inputs are limited to regular non-symlink files: 10,000
  files, 20,000 traversed entries, 64 MiB per file, and 512 MiB aggregate.
  Generic text requires strict UTF-8 and a maximum 1 MiB line; invalid input
  fails before the existing destination is changed.
- The complete pack is staged and source fingerprints are rechecked before
  publication. Handled generation/publication failures preserve or restore the
  previous pack. Replacing an existing non-empty directory on Windows is a
  two-rename rollback protocol, not an observer-atomic or crash-atomic swap.
- Current manifests omit the local source-folder path, but relative file names
  and copied content can still be sensitive.
- A qualified engagement owner should review the final pack before external sharing.
