# Product Page Drafts

Draft page copy for conservative website/product pages. These pages describe current local-first, export-based, foundation-stage behavior and should not be used to imply enterprise production readiness, direct ERP integration, compliance certification, audit opinions, legal signatures, customer adoption, ROI, or replacement of ERP, audit, GRC, or close platforms.

## Reconciliation And Stock-To-GL

Page headline:

Review stock movements against GL postings from local ERP exports.

Positioning:

ReconForge helps finance and operations teams inspect stock-to-GL differences from local CSV/XLSX exports. It supports configurable matching strategies, unmatched stock review, unmatched GL review, variance checks, and report outputs that can be reviewed locally.

What to show:

- Local input folder with exported stock and GL files.
- Reconciliation command examples.
- Excel and HTML outputs.
- Exception summaries and source-record traceability.
- Evidence binder generation for high-risk cases.

Boundary note:

This is export-based reconciliation support. It is not an ERP posting engine, direct connector, audit opinion, compliance certification, or replacement for a full enterprise reconciliation suite.

## Finance Controls Workflows

Page headline:

Run transparent finance controls from rule packs and local exports.

Positioning:

ReconForge rule packs help users run deterministic, explainable checks over exported ERP and operational data. Control packs can cover stock valuation, purchase-to-pay, WIP, service, fraud red flags, month-end close, and other review scenarios.

What to show:

- YAML rule-pack structure.
- Mapping validation.
- Rule result CSV/JSON outputs.
- Risk scoring and explanation notes.
- Control matrix exports.

Boundary note:

Rule packs support local review and evidence preparation. They do not certify controls, guarantee compliance, or replace professional judgment.

## Close And Review Workflow Foundations

Page headline:

Track local close and exception review state without a hosted workflow.

Positioning:

ReconForge includes local close checklist and review workflow foundations. Users can initialize close tasks, update statuses, export review registers, compare periods, and inspect DB-backed workflow foundations for account reconciliations, close tasks, exceptions, and metrics.

What to show:

- Local close checklist output.
- Review register export.
- Studio review status workflow.
- DB-backed close and exception foundation pages.
- Period comparison outputs.

Boundary note:

These are local workflow foundations. They are not enterprise close orchestration, production identity infrastructure, audit sign-off, or a hosted collaboration system.

## Evidence And Audit Preparation

Page headline:

Prepare local evidence folders and checksum manifests for review.

Positioning:

ReconForge can generate evidence folders, index files, review forms, source-record extracts, and checksum manifests from local outputs. These artifacts help teams organize review preparation and handoff packs.

What to show:

- Evidence binder index.
- Evidence manifest.
- Client handoff pack.
- Redaction options.
- Security and data-handling docs.

Boundary note:

Evidence outputs are preparation aids. Checksums are integrity aids, not legal signatures, non-repudiation controls, audit opinions, or compliance certification.

## Synthetic Enterprise Demo

Page headline:

Inspect platform foundations with fully synthetic demo data.

Positioning:

The synthetic enterprise demo generates multi-entity, multi-period local files and report outputs for accounts, close tasks, evidence, journal controls, intercompany, control testing, matching, unified exceptions, and metrics.

Commands:

```bash
reconforge demo enterprise --output output/enterprise_demo
reconforge demo enterprise --output output/enterprise_demo --db output/enterprise_demo/reconforge.db
```

What to show:

- `output/enterprise_demo/README.md`
- `output/enterprise_demo/demo_manifest.json`
- `output/enterprise_demo/reports/`
- `output/enterprise_demo/sample_evidence/`

Boundary note:

All demo data is synthetic. Do not present generated demo outputs as customer usage, adoption proof, ROI, or production evidence.

## Local API And Studio Foundations

Page headline:

Explore local API and Studio foundations for DB-backed workflows.

Positioning:

ReconForge includes local REST API and Studio foundations for selected DB-backed workflows. These surfaces help evaluate local accounts, close, exceptions, metrics, users/RBAC, audit events, and platform records.

What to show:

- Local API docs.
- Studio auth-required mode.
- DB-backed workflow pages.
- Local users/RBAC docs.
- Security questionnaire and deployment boundaries.

Boundary note:

The API and Studio foundations are local evaluation surfaces. They are not a hosted production platform, public internet deployment mode, managed identity service, or enterprise security certification claim.
