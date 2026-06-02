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

Report security issues privately to the maintainer or repository owner. Include:

- Affected command or module.
- Reproduction steps using synthetic or anonymized data.
- Impact and expected behavior.
- Any relevant dependency version.

Do not publish exploit details or sensitive sample data in public issues.

## Dependency and Workflow Posture

The repository includes:

- Ruff and Mypy checks.
- Pytest coverage.
- Bandit and pip-audit security workflow.
- CodeQL workflow for supported GitHub environments.
- Dependabot configuration for Python and GitHub Actions.
- Pre-commit hooks for formatting and basic file hygiene.

Security tooling supports maintainers, but it does not replace careful review of file handling, report output, connector logic, and user-supplied data.
