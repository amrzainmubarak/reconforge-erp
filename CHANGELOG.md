# Changelog

## v0.6.1 — Pilot Readiness Hardening

ReconForge ERP v0.6.1 focuses on post-productization hardening for credible local pilots, consultant demos, and cautious commercial evaluation while staying local-first, file-based, and export-oriented.

- Added client-pack redaction and exclusion controls, including `--redact-names`, `--redact-amounts`, `--exclude-raw-records`, `--summary-only`, `--exclude-evidence`, and optional manifest checksums.
- Added SHA-256 integrity manifests for evidence binders and optional checksum entries for client-pack manifests. These are checksums, not legal digital signatures.
- Added period trend reporting with new, recurring, resolved, high/critical, review-completion, accepted-risk, escalated, and top recurring theme outputs.
- Added export-based ERPNext, Microsoft Dynamics, and NetSuite profiles without direct connector claims.
- Added a Docker build workflow and Docker verification documentation while keeping Docker runtime verification explicitly unclaimed unless build/run commands pass in a live Docker environment.
- Added a compliance disclaimer, redaction controls guide, evidence-integrity guide, and updated security/commercial documentation.
- Added pilot proposal and client onboarding checklist documents for consultant-led evaluations.
- Added synthetic Odoo and SAP pilot case studies with clear no-customer, no-savings, and no-audit-opinion boundaries.
- Added a demo recording checklist, expanded demo video package, and static landing page foundation.
- Updated version metadata to `0.6.1`.

## v0.6.0

ReconForge ERP v0.6.0 focuses on productization and enterprise usability while staying local-first and file-based.

- Added Studio review status update actions that write to `output/review_state.json`.
- Added safe local POST handling, status validation, escaped rendering, and tests for Studio review updates.
- Added `reconforge mappings validate` for ERP mapping profile validation.
- Added `reconforge demo run` for a deterministic first-time-user workflow with reports, evidence, review state, and review register export.
- Added Control Value Summary sections to HTML and Excel reports.
- Added `reconforge report client-pack` for local consultant/client handoff folders.
- Added productization assessment, demo scenarios, client handoff docs, and practical 10-minute demo onboarding.
- Updated version metadata to `0.6.0`.

## v0.5.0

ReconForge ERP v0.5.0 adds the local exception review workflow foundation.

- Added file-based review state in `output/review_state.json` with allowed statuses: New, Under Review, Resolved, Accepted Risk, and Escalated.
- Added `reconforge review list`, `reconforge review set-status`, and `reconforge review export` CLI commands.
- Added optional `output/review_register.xlsx` export for audit-ready review status.
- Integrated review status, reviewer notes, and update metadata into evidence binder index, register, summaries, review forms, and audit trail JSON when review state exists.
- Added Studio exception filters for severity/risk level, exception type, review status, source file, search text, minimum amount, and sorting.
- Added review workflow documentation and tests for state handling, CLI commands, Studio filters, and evidence register integration.

## v0.4.0

ReconForge ERP v0.4.0 focuses on ERP mapping foundations for export-based Odoo and SAP workflows.

- Added rule-pack schema reference covering `pack.yml`, `rules.yml`, `mapping.yml`, `risk_model.yml`, supported operators, severity, confidence, risk impact, evidence fields, examples, and validation commands.
- Expanded the Odoo inventory valuation control pack with practical export mapping guidance, field candidates, join keys, quality checks, stronger rules, expected exceptions, and sample commands.
- Expanded the SAP MB51/FAGLL03 control pack with practical MB51 and FAGLL03/FBL3N export mapping guidance, field candidates, join keys, quality checks, stronger rules, expected exceptions, and sample commands.
- Updated Odoo and SAP export guides with field-level mapping notes and local workflow commands.
- Added strategic planning docs for repository assessment, competitor intelligence, category leadership, product roadmap, adoption engine, commercial strategy, trust/security, and thought-leadership content.
- Added structure tests for v0.4.0 schema docs and ERP mapping profiles.
- Added README positioning for export-based ERP mapping profiles and no-cloud-upload core workflows.

## v0.3.0

ReconForge ERP v0.3.0 expands the project into a stronger pre-1.0 platform release.

- Added advanced rule operators for duplicate, cross-file, variance, date, and aging controls.
- Added rule explanation command.
- Expanded to 15 control packs with risk models and sample commands.
- Added risk intelligence package.
- Added evidence binder review forms, HTML index, and Excel evidence register.
- Added anonymization profiles and amount noise.
- Added dealership and service synthetic data profiles plus currency option.
- Added benchmark HTML output and engine registry.
- Added matching strategies with confidence, similarity, and review-required metadata.
- Added offline exception explanation layer.
- Added plugin/connector foundation.
- Added expanded Studio pages for rule results and risk matrix.
- Added market intelligence, category strategy, risk, anonymization, synthetic data, AI, plugin, security, and privacy documentation.

## v0.2.0

ReconForge ERP v0.2.0 upgrades the project into a broader local-first ERP reconciliation and audit intelligence platform.

- Added YAML rule engine with validation, listing, and execution CLI commands.
- Added control packs for audit basics, Odoo inventory valuation, SAP MB51/FAGLL03, workshop spare parts, fleet maintenance, manufacturing WIP, and dealership service.
- Added audit evidence binder for High and Critical exceptions.
- Added data anonymizer that preserves referential integrity across ERP exports.
- Added synthetic data generator for workshop, manufacturing, and fleet scenarios.
- Added benchmark engine with Pandas support and optional DuckDB handling.
- Added ReconForge Studio local web interface.
- Added market research, product strategy, architecture, benchmark, Studio, plain-English, Arabic, playbook, launch, OpenAI OSS application, commercial strategy, and release documentation.
- Added security workflow, CodeQL workflow, Dependabot, and pre-commit configuration.
- Updated README, Dockerfile, Makefile, CI, security, contributing, and roadmap materials.

## v0.1.0

Initial open-source release of ReconForge ERP.

- Added Typer CLI with `init`, `validate`, `reconcile`, `report`, `dashboard`, and `doctor` commands.
- Added CSV and Excel readers for ERP exports.
- Added schema validation for required columns, data types, duplicate references, amount consistency, and master-data references.
- Added stock movement to GL reconciliation with exact, fuzzy reference, amount/date proximity, and exception matching.
- Added work-order controls for spare-parts issues, direct purchase fitting, old-part returns, invoice gaps, post-closure issues, and cancelled PO linkage.
- Added WIP aging report with configurable buckets and risk scoring.
- Added Excel management pack, CSV/JSON outputs, Markdown summary, and HTML dashboard report.
- Added local FastAPI dashboard server.
- Added synthetic sample data, documentation, Docker, Docker Compose, Makefile, tests, Ruff, Mypy, and GitHub Actions CI.
