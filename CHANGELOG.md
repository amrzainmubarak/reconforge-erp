# Changelog

## Unreleased

- Added an experimental read-only React Studio dashboard, native exception queue, evidence binder, and inventory control center backed by four versioned synthetic-only local contracts, with a deterministic executive decision brief, close-readiness signal, guided control story, control-domain/entity health, runtime validation, responsive/RTL/accessibility behavior, deterministic exception IDs, filtering, FIFO valuation/reversal/layer views, and verified screenshots.
- Added `reconforge demo showcase`, `make showcase`, `make showcase-serve`, and a root `DEMO.md` presenter guide for one cohesive generated enterprise package, strict Studio bundle, production web build, and five-minute local walkthrough.
- Added bounded Python generation for the Studio overview/exception/evidence/inventory bundle. Evidence browser metadata excludes source paths and validates SHA-256 values; inventory quantities and values remain exact decimal strings, and inconsistent valuation/reversal/layer records are rejected.
- Added a typed read-only runtime module registry plus `reconforge modules list`, `show`, and `validate` commands. Registry entries distinguish maturity from capability status and declare dependencies, migrations, permissions, interfaces, contracts, data classification, retention/activation notes, and test evidence.
- Added JSON Schemas and ADRs for the modern Studio contracts and runtime module registry.
- Replaced deprecated naive `datetime.utcnow()` generation with shared timezone-aware UTC helpers while preserving existing second-precision `Z` timestamp contracts.
- Added SQLite migration 7 and the experimental `platform.master-data` module for governed organizations, legal entities, branches, currency references, and non-overlapping fiscal periods, with RBAC, audit events, authenticated API routes, CLI commands, safe v6 upgrade coverage, and a versioned path-free snapshot schema.
- Preserved migration-7 master data in local JSON backups and made supported pre-v7 backups restore into their source schema before upgrading to the current schema.
- Added migration 8 and the experimental `finance.core` module: governed charts/accounts, dimensions, journals, exact minor-unit balanced control entries, atomic reference rechecks, SoD validation, immutable Validated/Voided records, trial-balance/snapshot contracts, API/CLI surfaces, and schema-aware backup/restore coverage.
- Added migration 9 and the experimental `inventory.core` module: units, item references, warehouse/location hierarchy, lot/serial traceability, exact-quantity Draft/Posted/Voided movements, atomic stock and serial checks, SoD posting, immutable Posted records, derived on-hand and deterministic exception contracts, API/CLI surfaces, and schema-aware backup/restore coverage.
- Added migration 10 to `inventory.core`: immutable physical-count snapshots, exact count results, reasoned submission/approval/cancellation, known-user SoD, stale-balance rejection, generated Draft variance adjustments, exact reorder thresholds and deterministic advice, repository isolation, strict API/CLI/contracts, backup/export recovery, and read-only synthetic Studio views. This does not implement purchasing, valuation, finance posting, or ERP writeback.
- Added migration 11 to `inventory.core`: entity FIFO policies, exact inbound cost evidence, chronological cost layers and immutable consumptions, Draft/Approved/Cancelled lifecycle, known-user SoD, balanced Finance Core Draft generation, movement-void protection, repository isolation, strict API/CLI/contracts, schema-aware backup/restore/export, and synthetic read-only Studio visibility. This does not implement AVCO, landed or manufacturing cost, automatic Finance Core validation, statutory posting, or ERP writeback.
- Added migration 12 to `inventory.core`: exact whole-valuation reversal through a separately Posted mirror movement, immutable FIFO `Restore`/`Remove` effects, dependency-order protection for consumed inbound layers, debit/credit-swapped Finance Core Drafts with copied dimensions, protected movement/finance evidence, separate RBAC/SoD, repository isolation, strict API/CLI/contracts, schema-aware backup/restore/export, and synthetic read-only Studio visibility. This does not implement partial or reversal-of-reversal orchestration, automatic Finance Core validation, statutory posting, or ERP writeback.

## v0.7.0 — Foundation-Stage Local Platform Readiness

ReconForge ERP v0.7.0 is a foundation-stage release for local-first, export-based pilot evaluation. It expands self-hosted/local-capable foundations for finance controls, reconciliation workflows, synthetic demos, support readiness, and conservative launch materials without claiming hosted production service readiness, direct ERP connectors, certification, audit opinions, legal signatures, customer traction, ROI, or platform replacement.

- Added foundations for the local platform backbone: SQLite DB/audit, local users/RBAC, workflow state machine, REST API, Studio auth-required mode, DB import/export, backup bridge, and supporting security/roadmap documentation.
- Added foundations for DB-backed finance workflows: account reconciliations, close management, approvals/certification metadata, evidence registry, journal controls, intercompany, controls testing, matching, unified exceptions, and metrics.
- Added Studio DB pages and local API route foundations for accounts, close, exceptions, and metrics while keeping the workflow local-first and export-based.
- Added local close checklist workflow commands: `reconforge close init`, `reconforge close list`, `reconforge close set-status`, and `reconforge close report`.
- Added lightweight reconciliation certification metadata fields to local review state and review register exports. These fields are workflow metadata only and are not legal sign-off, audit opinions, compliance certifications, or digital signatures.
- Added local variance analysis command: `reconforge analyze variance`.
- Added rule-pack-derived control matrix export command: `reconforge controls matrix`.
- Added read-only Studio pages for local close checklist, variance analysis, control matrix, and evidence coverage.
- Added an export-based Oracle inventory/GL mapping profile without direct connector claims.
- Added `reconforge mappings profile-template` for local generic CSV profile authoring templates.
- Added JSON schema documentation for close checklist, certification metadata, variance report, control matrix, and profile template outputs.
- Expanded management pack KPIs with unresolved high-risk count, recurring exception count when period comparison output exists, close checklist completion when close state exists, evidence coverage when evidence output exists, accepted risk count, and review completion signals.
- Added strategy documents for global capability benchmarking, platform blueprint, feature gaps, differentiation, and the next release roadmap.
- Added documentation for close workflow, variance analysis, control matrix, and reconciliation certification metadata.
- Added focused tests for new CLI commands, malformed inputs, status validation, output files, certification metadata, and HTML/Markdown escaping behavior.
- Added the synthetic enterprise demo package for generated multi-entity platform-foundation walkthroughs using synthetic data only.
- Added pilot/support/buyer readiness docs: support playbook, pilot onboarding checklist, buyer FAQ, draft implementation packages, release readiness checklist, and security questionnaire updates.
- Added conservative website and launch copy drafts with a claim-boundary guide for local-first/export-based positioning.
- Added release readiness and deployment smoke documentation for local CLI, API, Studio, synthetic demo, DB, and Docker verification commands.
- Updated version metadata to `0.7.0`.

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
