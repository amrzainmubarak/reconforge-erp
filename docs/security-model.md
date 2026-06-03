# Security Model

ReconForge ERP is local-first. The default workflow reads local CSV/XLSX exports and writes local reports.

## Security Principles

- No cloud upload by default.
- No paid API requirement.
- No secrets in control packs.
- No live ERP credentials in the core workflow.
- Anonymization available for safe sharing.
- Evidence folders treated as sensitive audit files.

## Threats Considered

- Accidental commit of live ERP exports.
- Sensitive values in generated reports.
- Unsafe export-adapter file handling.
- Dependency vulnerabilities.
- Over-trusting AI-generated text.

## Controls

- SECURITY guidance.
- Pre-commit hooks.
- CI with Ruff, Mypy, Pytest.
- Security workflow for Bandit and pip-audit.
- CodeQL workflow.
- OpenSSF Scorecard workflow.
- CycloneDX SBOM workflow.
- Dependabot.

## User Responsibilities

Run ReconForge in trusted environments, review generated outputs before sharing, and anonymize sensitive exports.
