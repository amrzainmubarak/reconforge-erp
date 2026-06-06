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
- Local SQLite database foundation with schema migrations is available for new DB-backed workflows.
- Local audit event hash chaining provides checksum integrity aids for appended audit events. It is not a legal digital signature, compliance certification, audit opinion, or non-repudiation guarantee.
- Local users and RBAC are available for DB-backed workflow foundations. Passwords are hashed with stdlib PBKDF2-HMAC-SHA256 and per-user salts; plaintext passwords must not be stored, logged, documented, or printed.
- Local workflow state transitions can enforce transition rules, required reasons, RBAC checks for local users, and SoD primitives. This is not a legal approval system, audit opinion, or compliance certification.
- SSO, SCIM, hosted identity, and SaaS multi-tenancy are not implemented.
- Local RBAC is not SOC/ISO/SOX compliance, production enterprise identity, or SaaS authentication.

## User Responsibilities

Run ReconForge in trusted environments, review generated outputs before sharing, and anonymize sensitive exports.
