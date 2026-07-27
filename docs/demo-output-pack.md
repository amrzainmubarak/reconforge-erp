# Demo Output Pack

This guide explains how to generate and share synthetic ReconForge ERP demo outputs safely. It does not include generated binary files.

## Generate Synthetic Demo Outputs

Run the complete synthetic demo:

```bash
reconforge demo run --output output/demo
```

Generate a summary-only client pack:

```bash
reconforge report client-pack --input output/demo --output output/demo_client_pack --summary-only
```

Generate a more conservative redacted client pack:

```bash
reconforge report client-pack --input output/demo --output output/demo_client_pack_redacted --redact-names --redact-amounts --exclude-raw-records --include-manifest-checksums
```

## Files That May Be Shareable After Review

For synthetic demo data only, these outputs are usually reasonable to review for sharing:

- `output/demo/summary.md`
- `output/demo/executive_report.html`
- `output/demo/dashboard.html`
- `output/demo_client_pack/handoff_summary.md`
- `output/demo_client_pack/data_privacy_note.md`
- `output/demo_client_pack/files_manifest.json`
- `output/demo_client_pack_redacted/`

Review every file before sharing, even when the input is synthetic.

## Files To Review Carefully

These outputs can contain row-level records, identifiers, names, amounts, notes, and exception details:

- `management_pack.xlsx`
- `management_pack.json`
- `review_register.xlsx`
- `review_state.json`
- `evidence/`
- raw CSV/JSON extracts
- any unredacted client pack

Do not share these externally unless they are synthetic or intentionally anonymized and reviewed.

## Avoid Sharing Private ERP Data

- Never use live ERP exports for public demos.
- Use `reconforge demo run` or anonymized exports.
- Check hidden workbook sheets before sharing Excel files.
- Prefer `--summary-only` or redaction flags for external demo packs.
- Exclude raw records when recipients do not need row-level evidence.

## Packaging Demo Outputs Later

If the project later publishes sample outputs as a release asset:

- regenerate from synthetic data only
- document the exact command used
- review HTML, Markdown, JSON, CSV, and Excel files manually
- include a manifest describing the synthetic source
- do not include private ERP exports, live identifiers, or unreviewed generated files

## What Not To Claim

Do not claim that demo outputs prove:

- real customer adoption
- audit sign-off or audit opinion support
- legal, tax, or compliance certification
- enterprise production readiness
- Docker runtime verification

Demo outputs show what the local workflow can generate from synthetic data.
