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
| `--include-manifest-checksums` | Adds SHA-256 hashes for included files in `files_manifest.json`. |

## Important Limitations

- Redaction is applied only to copied/generated client-pack files.
- The original `output/` folder is not modified.
- Binary workbooks are excluded when redaction is requested because text-level redaction cannot safely rewrite every workbook cell.
- Redaction is a practical safeguard, not a guarantee that every sensitive value has been removed.
- A qualified engagement owner should review the final pack before external sharing.
