# AGENTS.md

Instructions for Codex, Copilot, and other AI coding agents working on ReconForge ERP.

## Project Overview

ReconForge ERP is a local-first, export-based ERP reconciliation toolkit for stock-to-GL matching, WIP/work-order controls, rule packs, mapping validation, review workflows, evidence binders, and client handoff packs.

The project is currently released as **v0.6.1 - Pilot Readiness Hardening**. It is early-stage and should be described conservatively.

## Core Local-First Rule

Core workflows must stay local-first:

- Read user-provided CSV/XLSX exports from local paths.
- Write reports, review state, evidence, and client packs to local paths.
- Do not add SaaS, cloud upload, hosted storage, telemetry, or paid API dependencies for core workflows.
- Do not describe export profiles as live or direct ERP connectors.

## Development Setup

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
pre-commit install
```

If an installed `reconforge` console script appears stale after a version or CLI change, reinstall:

```bash
python -m pip install -e ".[dev]" --force-reinstall
```

## Required Quality Commands

Run these before proposing or merging changes:

```bash
python -m ruff check .
python -m mypy reconforge
python -m pytest
```

## Required Security Checks

```bash
python -m bandit -q -r reconforge
pip-audit -r requirements.txt
```

When a change touches file handling, generated HTML, YAML loading, downloads, Studio routes, evidence output, client packs, or mapping validation, add targeted tests for the security behavior.

## Required Test Commands

Use the full test suite for broad changes:

```bash
python -m pytest
```

Use focused tests during development:

```bash
python -m pytest tests/test_safe_paths.py
python -m pytest tests/test_reports.py
python -m pytest tests/test_mapping_validation_cli.py
python -m pytest tests/test_review_workflow.py
```

## CLI Smoke Commands

```bash
python -m reconforge.cli doctor
reconforge validate examples/sample_data
reconforge demo run --output output/demo
reconforge report management-pack --input examples/sample_data --config config/reconforge.yml --output output
reconforge report client-pack --input output --output output/client_pack --summary-only
```

Mapping-profile smoke checks:

```bash
reconforge mappings validate --pack control-packs/odoo-inventory-valuation
reconforge mappings validate --pack control-packs/sap-mb51-fagll03
reconforge mappings validate --pack control-packs/erpnext-stock-gl
reconforge mappings validate --pack control-packs/dynamics-inventory-gl
reconforge mappings validate --pack control-packs/netsuite-inventory-gl
```

## How To Add Rule Packs

Add rule packs under `control-packs/<pack-name>/` with:

- `pack.yml`
- `rules.yml`
- `mapping.yml`
- `risk_model.yml` when risk scoring changes
- `README.md`
- `expected-exceptions.md`
- `sample-command.md`

Rules should be practical, explainable, deterministic, and testable with synthetic or anonymized data. Validate YAML with safe parsing only and route all rule evaluation through supported operators and pydantic models.

## How To Add ERP Export Profiles

ReconForge supports export-based profiles, not live ERP integrations. New profiles should:

- Describe the ERP export/report source and expected CSV/XLSX files.
- Map fields into canonical ReconForge files before reconciliation.
- Preserve source-document traceability.
- Include sanitized header examples, not real client data.
- Include mapping validation tests or fixture coverage when behavior changes.
- Avoid claiming direct ERP connectivity, sync, certification, or official vendor endorsement.

Use `reconforge mappings profile-template --output output/profile_template` to generate a local starter mapping template and authoring guide. Keep generated profile examples sanitized and validation-friendly, and update `docs/schemas/` when adding a stable local file contract.

## How To Add Close, Certification, Variance, Or Control Matrix Features

- Keep close checklist state local JSON only and use allowed statuses: Not Started, In Progress, Blocked, Complete, Not Applicable.
- Treat prepared/reviewed and certification fields as workflow metadata only. Do not imply audit opinions, legal sign-off, compliance certification, or digital signatures.
- Escape all generated HTML and Markdown-visible user-controlled values.
- Add tests for malformed inputs, missing local files, status validation, and output existence.

## How To Update Documentation

Documentation must stay accurate, conservative, and consistent with released behavior.

- Update README only for high-level user-facing changes.
- Update `docs/index.md` when adding important docs.
- Update security docs when changing file handling, generated HTML, evidence, redaction, workflows, or dependency posture.
- Update release docs and changelog when release behavior changes.
- Do not claim adoption, customer usage, enterprise production readiness, legal assurance, audit opinions, compliance certification, or Docker runtime verification unless documented evidence exists.

## How To Handle Releases

Use `docs/maintainers/release-process.md` as the source checklist. At minimum:

- Confirm version numbers in `pyproject.toml`, README, docs, and release notes.
- Run quality, security, CLI smoke, and mapping validation commands.
- Run Docker build/run checks before claiming Docker runtime verification.
- Update `CHANGELOG.md`.
- Keep release notes factual and scoped to observed behavior.
- Do not release generated binaries or demo output unless intentionally reviewed and documented.

## How To Handle PR Review Comments

- Treat review comments as bug reports against the proposed change.
- Make the smallest coherent fix.
- Add tests when the comment identifies a behavioral or security gap.
- Re-run the relevant focused test first, then the full quality gate when feasible.
- Summarize what changed and which validation commands passed.
- Do not overwrite generated summaries, reports, or user-edited docs without checking the current file content.

## Security Rules

Always apply these rules:

- No raw exception leakage into CLI, HTML, Studio, report, or API-style output.
- Escape all user-controlled values before inserting into HTML.
- URL-quote href path segments and avoid unsafe concatenation.
- No path traversal through input paths, output paths, route parameters, archive paths, or report links.
- No direct file serving from user input. Use allowlists, registries, safe suffix checks, and resolved-path checks.
- Use safe YAML parsing only.
- Never include live customer, supplier, employee, asset, invoice, GL, or financial data in fixtures or docs.
- Do not add fake claims or unverified marketing language.

## Commercial And Legal Wording Rules

Do not claim:

- Audit opinions, audit sign-off, or assurance conclusions.
- Legal, tax, regulatory, or compliance certification.
- SOC 2, ISO, GDPR, SOX, IFRS, GAAP, audit, or tax compliance unless clearly framed as user-controlled workflow support and backed by implemented behavior.
- Real customers, pilots, adoption, testimonials, logos, or production use unless documented.
- Direct ERP connectors or vendor-certified integrations.
- Enterprise production readiness.

Preferred wording:

- "supports local evidence preparation"
- "helps review export-based reconciliation workflows"
- "provides checksum integrity aids"
- "pilot-ready open-source toolkit"
- "early-stage"

## Preferred PR Style

- Keep scope narrow.
- Prefer deterministic functions and schema-driven validation.
- Add focused tests for new behavior and regressions.
- Keep docs updates close to the changed behavior.
- Explain finance/audit control logic in plain English.
- Keep generated output out of git unless it is a small, reviewed documentation artifact.

## What Not To Do

- Do not add cloud upload, SaaS behavior, telemetry, or hosted storage.
- Do not introduce direct ERP credential handling.
- Do not broaden claims to production, certified, or customer-proven status.
- Do not hand-roll unsafe path, YAML, or HTML handling.
- Do not hide reconciliation decisions in opaque matching logic.
- Do not change CLI command semantics without tests and docs.
- Do not remove existing security, CI, evidence, redaction, or review workflow behavior.
