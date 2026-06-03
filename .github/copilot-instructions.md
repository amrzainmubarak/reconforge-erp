# Copilot Review Instructions

ReconForge ERP is an early-stage, local-first, export-based ERP reconciliation toolkit. Reviews should protect maintainability, security credibility, and honest documentation more than feature volume.

## Project Goals

- Keep reconciliation, rule packs, mapping validation, evidence, reports, review state, and client handoff workflows local-first.
- Support finance, audit, ERP, stores, workshop, fleet, and SME users working from CSV/XLSX exports.
- Improve controls, tests, docs, and maintainer workflows without overstating maturity.

## Code Style

- Python 3.11+ with type hints.
- Deterministic reconciliation logic.
- Schema-driven validation over implicit assumptions.
- Small functions that preserve source-document traceability.
- Existing Typer, pydantic, pandas, and report-writer patterns should be reused.

## Testing Requirements

PRs should run:

```bash
python -m ruff check .
python -m mypy reconforge
python -m pytest
python -m bandit -q -r reconforge
```

Changes to mappings, rule packs, reports, evidence, Studio, safe paths, redaction, or CLI behavior need targeted tests.

## Security Review Priorities

- Unsafe href escaping or unquoted path segments.
- Raw exception rendering in HTML, Studio, CLI, or report output.
- Path traversal through input/output paths, route parameters, archive paths, or generated links.
- Direct file serving from user-controlled input.
- Unsafe YAML loading.
- Leaking real or private ERP data in fixtures, docs, screenshots, or generated samples.

## Documentation Wording Boundaries

Docs must not claim:

- real adoption, customer usage, testimonials, or production deployment
- audit opinions or compliance/legal/tax certification
- direct ERP connectors or vendor-certified integrations
- Docker runtime verification unless the documented build and run commands pass
- signed artifacts unless signing exists

Use conservative wording such as "local-first", "export-based", "early-stage", "pilot-ready open-source toolkit", and "integrity aid".

## Local-First Constraints

Do not introduce cloud upload, SaaS flows, telemetry, paid API dependencies, or live ERP credential handling for core workflows.

## PR Review Checklist

- Does the change preserve existing CLI, Studio, report, evidence, redaction, and review workflows?
- Are tests included for new behavior and regressions?
- Are generated HTML values escaped and links safely encoded?
- Are file paths resolved safely?
- Are docs accurate for v0.6.1 behavior?
- Are sample data and examples synthetic or anonymized?
- Are rule-pack and export-profile changes explainable to finance/audit users?

## Common Failure Modes Seen In Prior Work

- Unsafe href escaping.
- Raw exception rendering.
- Path traversal risks in download routes or output packaging.
- Synthetic ID matching mistakes that break referential integrity.
- Overwriting generated summaries instead of preserving or regenerating them intentionally.
- Current-working-directory assumptions instead of explicit input/output paths.

## Evaluating New ERP Export Profiles

- Confirm the profile is export-based and uses CSV/XLSX files.
- Check that required fields map to canonical ReconForge files.
- Require sanitized headers and synthetic samples only.
- Validate traceability from source export rows to reconciliation outputs.
- Avoid vendor endorsement, certified integration, or direct connector language.

## Evaluating Docs For Overclaims

Flag wording that implies customer proof, compliance certification, legal assurance, audit sign-off, direct connectivity, production readiness, or measured security scores unless the repository contains evidence.
