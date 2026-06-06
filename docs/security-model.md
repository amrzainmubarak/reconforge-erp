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
- Local REST API sessions store hashed tokens only, reject disabled users, and bind to `127.0.0.1` by default. The API is a local/self-hosted foundation and is not public internet deployment guidance.
- Studio trusted local mode remains the default. Optional `reconforge studio --require-auth --db output/reconforge.db` requires a migrated local DB, local login, an HTTP-only session cookie backed by hashed session-token storage, logout/revocation, disabled-user rejection, and a local RBAC check for exception review status updates.
- The DB import/export bridge writes local JSON exports and local backup files only. Sanitized exports exclude password hashes, salts, and session-token hashes. Backups may include sensitive local business data and local password hashes needed for restore, but they exclude raw tokens and the `api_sessions` table. Backup files must be protected and are not cloud backup, SaaS storage, enterprise disaster recovery, or a compliance certification.
- DB-backed account, close, approval, evidence, journal, intercompany, control testing, matching, exception, and metric workflows use local audit events where practical. RBAC and SoD checks apply when actions are performed by known local users. Trusted local CLI labels remain available for single-user local operation.
- Evidence checksums and audit-event hashes are integrity aids only. They are not digital signatures, legal approval, non-repudiation, audit opinions, or compliance certifications.
- SSO, SCIM, hosted identity, and SaaS multi-tenancy are not implemented.
- Local RBAC and API sessions are not SOC/ISO/SOX compliance, production enterprise identity, OAuth/SAML/SCIM/SSO, or SaaS authentication.

## User Responsibilities

Run ReconForge in trusted environments, review generated outputs before sharing, and anonymize sensitive exports.
