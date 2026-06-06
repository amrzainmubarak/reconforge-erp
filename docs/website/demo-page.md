# Demo Page Copy

Draft copy for a website demo page. This page should be used only for local-first, export-based, synthetic, or sample-data walkthroughs.

## Headline

Run ReconForge locally with sample and synthetic enterprise demo data.

## Short Description

ReconForge demos are designed to be repeatable, local-first, and safe for public walkthroughs. They use sample or synthetic data and generate local reports, review outputs, evidence folders, and demo manifests without cloud upload.

## Standard Demo

Run:

```bash
reconforge demo run --output output/demo
```

Review:

- `output/demo/executive_report.html`
- `output/demo/management_pack.xlsx`
- `output/demo/review_register.xlsx`
- `output/demo/evidence/index.html`
- `output/demo/client_pack/handoff_summary.md`

## Synthetic Enterprise Demo

Run:

```bash
reconforge demo enterprise --output output/enterprise_demo
```

Optional local DB demo state:

```bash
reconforge demo enterprise --output output/enterprise_demo --db output/enterprise_demo/reconforge.db
```

Review:

- `output/enterprise_demo/README.md`
- `output/enterprise_demo/demo_walkthrough.md`
- `output/enterprise_demo/demo_manifest.json`
- `output/enterprise_demo/reports/`
- `output/enterprise_demo/sample_evidence/`

## Data Boundary

All public demo material should use sample or synthetic data. Do not use live customer data, private ERP exports, client evidence folders, backups, SQLite databases, or unredacted generated packs in public demos.

## What The Demo Shows

- Local CSV/XLSX-style export workflows.
- Stock-to-GL and management-pack outputs.
- Review state and review register outputs.
- Evidence binder and client handoff packaging.
- Synthetic accounts, close tasks, evidence, journal controls, intercompany cases, control testing, matching, unified exceptions, and metrics.

## What The Demo Does Not Show

- Real customers.
- Customer logos.
- Testimonials.
- ROI or savings proof.
- Compliance certification.
- Audit opinions.
- Direct ERP connector behavior.
- Hosted production service behavior.

## Screenshot Guidance

Use existing repository assets or freshly generated local demo outputs only. Do not claim screenshots are from customer environments. If screenshots are not refreshed for a website update, describe them as local generated sample/demo outputs only.
