# Security Model

ReconForge ERP is local-first. The default workflow reads local CSV/XLSX exports and writes local reports.

## Security Principles

- No cloud upload by default.
- No paid API requirement.
- No secrets in control packs.
- No live ERP credentials in the core workflow.
- Local anonymization is available as a risk-reduction aid; it is not proof that data is safe to share.
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
- Security workflow definitions for Bandit, locked Python/server and npm audits, and checksum-pinned redacted history/tree secret scans.
- CodeQL workflow.
- OpenSSF Scorecard workflow.
- Release-integrated, exact-subject CycloneDX 1.7 SBOM definition and local deterministic package/source fixtures.
- Closed supply-chain and expiring exception policy with pre-registry candidate gates; hosted enforcement remains unverified.
- Versioned bounded tabular preflight plus a closed direct-parser inventory reject the documented hostile CSV/XLSX cases before canonical parsing; this is not malware, upload, connector, source-authenticity, or legacy-XLS-internal assurance.
- Dependabot.
- Local SQLite database foundation with schema migrations is available for new DB-backed workflows.
- Local audit event hash chaining provides checksum integrity aids for appended audit events. It is not a legal digital signature, compliance certification, audit opinion, or non-repudiation guarantee.
- Local users and RBAC are available for DB-backed workflow foundations. Passwords are hashed with stdlib PBKDF2-HMAC-SHA256 and per-user salts; plaintext passwords must not be stored, logged, documented, or printed.
- Local workflow state transitions can enforce transition rules, required reasons, RBAC checks for local users, and SoD primitives. This is not a legal sign-off system, audit opinion, or compliance certification.
- Local REST API sessions store hashed tokens only, reject disabled users, and bind to `127.0.0.1` by default. The API is a local/self-hosted foundation and is not public internet deployment guidance.
- Studio trusted local mode remains the default. Optional `reconforge studio --require-auth --db output/reconforge.db` requires a migrated local DB, local login, an HTTP-only session cookie backed by hashed session-token storage, logout/revocation, disabled-user rejection, and a local RBAC check for exception review status updates.
- The DB import/export bridge writes local JSON exports and local backup files only. Sanitized exports exclude password hashes, salts, and session-token hashes. Backups may include sensitive local business data and local password hashes needed for restore, but they exclude raw tokens and the `api_sessions` table. Backup files must be protected and are not cloud backup, SaaS storage, enterprise disaster recovery, or a compliance certification.
- DB-backed account, close, approval, evidence, journal, intercompany, control testing, matching, exception, and metric workflows use local audit events where practical. RBAC and SoD checks apply when actions are performed by known local users. Trusted local CLI labels remain available for single-user local operation.
- Organization master-data reads and mutations use explicit `master_data.read` / `master_data.manage` permissions. Codes, names, dates, currency references, relationships, period overlap, status transitions, and snapshot fields are bounded; snapshots contain no database paths, credentials, tokens, or evidence paths.
- Finance-core reads, draft/master mutations, and validation/void actions use separate permissions. Exact minor units, balance checks, period/date scope, required dimensions, account posting flags, SQLite immutability triggers, and known-user creator/validator separation protect the local control-ledger foundation. This is not source-ERP posting, a statutory ledger, or audit assurance.
- Inventory reads, master/Draft mutations, posting/void, count management/approval, reorder-rule mutation, valuation management/approval, and valuation-reversal management/approval use separate permissions. Exact scaled quantities and minor-unit values, direction/scope checks, protected-location stock checks, serial constraints, immutable count/valuation/reversal evidence, stale-balance and chronological FIFO checks, exact mirror-line checks, SQLite triggers, and known-user creator/poster/approver separation protect the local foundations. `Posted` affects local derived on-hand only; approved counts create at most a Draft adjustment, reorder signals are advice, and Approved valuations or reversals prepare only balanced Finance Core Drafts. Approved reversal effects, finance lines/dimensions, mirror movement, and finance reference are protected from silent mutation or voiding. None implies ERP writeback, fulfillment, physical-count certification, automatic accounting validation, purchasing, statutory reporting, or audit assurance.
- Evidence checksums and audit-event hashes are integrity aids only. They are not signature workflows, legal sign-off, non-repudiation guarantees, audit opinions, or compliance certifications.
- SSO, SCIM, hosted identity, and SaaS multi-tenancy are not implemented.
- Local RBAC and API sessions are not SOC/ISO/SOX compliance, production enterprise identity, OAuth/SAML/SCIM/SSO, or SaaS authentication.

## User Responsibilities

Run ReconForge in trusted environments and review every generated output before
sharing. Treat explicit private anonymization maps as source-sensitive data.
Anonymization reduces selected risks but does not establish safe publication.
