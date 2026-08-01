# Security Policy

ReconForge ERP is designed for local processing of sensitive ERP exports. By default, it does not upload data to cloud services, call paid APIs, or require internet access for reconciliation after dependencies are installed.

## Sensitive Data Handling

Do not commit or publish:

- Customer names, customer codes, contacts, or addresses from live systems.
- Supplier records from live systems.
- Employee names, user IDs, or approval chains.
- Vehicle, equipment, serial, or asset identifiers from live systems.
- Real GL accounts, amounts, invoices, purchase orders, or work orders.
- Access tokens, database credentials, API keys, ERP passwords, or connection strings.
- Excel files with hidden sheets containing live data.

## Anonymizing ERP Exports

Use the built-in anonymizer before sharing examples:

```bash
reconforge anonymize --input examples/sample_data --output examples/anonymized_data --seed 42 --date-shift-days 30
```

The anonymizer preserves referential integrity so the same original work order, source document, invoice, customer, supplier, or equipment identifier receives the same masked value across files.

For sensitive financial values, use:

```bash
reconforge anonymize --input live_exports --output anonymized_exports --mask-amounts --seed 42
```

## Safe Local Processing

- Run ReconForge ERP in a trusted local environment.
- Store generated outputs securely because reports can contain the same sensitive values as inputs.
- Treat evidence binder folders as audit files.
- Review generated CSV, JSON, Markdown, Excel, and HTML files before sharing them.
- Keep control packs and mapping files free of secrets.

## Vulnerability Reports

The preferred channel is GitHub private vulnerability reporting when the
repository owner has enabled it:

https://github.com/amrzainmubarak/reconforge-erp/security/advisories/new

Live repository API verification on 2026-08-01 reported that private
vulnerability reporting was disabled. Until the owner enables and tests it,
contact the repository owner privately before sharing details. Do not open a
public issue for an unpatched vulnerability. Review solicitation remains blocked
if no private channel is operational.

Maintainer response targets:

- Acknowledge a vulnerability disclosure within 7 days when feasible.
- Provide a first status update or remediation plan within 30 days when feasible.
- Coordinate public disclosure only after a fix, mitigation, or documented non-applicability decision is ready.

Include:

- Affected command or module.
- Reproduction steps using synthetic or anonymized data.
- Impact and expected behavior.
- Any relevant dependency version.

Do not publish exploit details or sensitive sample data in public issues, pull requests, or discussions.

## Dependency and Workflow Posture

The repository includes:

- Ruff and Mypy checks.
- Pytest coverage.
- Bandit plus locked Python/server and npm audit definitions on change and schedule.
- CodeQL workflow for supported GitHub environments.
- OpenSSF Scorecard workflow on `main`/`master` pushes, schedule, and manual dispatch as a repository security maturity check.
- Release-integrated, exact-subject CycloneDX SBOM definitions for source, wheel, sdist, and image candidates.
- Checksum-pinned, redacted Gitleaks definitions for full history and the checked tree.
- Closed dependency/secret policy and bounded exception registry with fail-closed pre-registry release gates.
- Weekly Dependabot configuration for Python, npm, Docker, and GitHub Actions.
- Pre-commit hooks for formatting and basic file hygiene.

Security tooling supports maintainers, but it does not replace careful review of file handling, report output, export-profile logic, dependencies, credentials, and user-supplied data. Local scans and workflow definitions are visibility aids, not proof of hosted enforcement, package safety, certification, or a signed release.
