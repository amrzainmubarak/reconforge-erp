# Support Playbook

This playbook is a draft, non-contractual support guide for ReconForge ERP maintainers, pilot reviewers, and implementation partners. It is not an SLA, warranty, managed service commitment, or production support contract.

ReconForge support should preserve the local-first, export-based model. Do not request live customer data, secrets, credentials, ERP passwords, API tokens, private financial statements, employee data, supplier bank details, or unredacted invoice, payroll, tax, GL, or customer records in public channels.

## Issue Intake Checklist

- Confirm the ReconForge version or Git commit.
- Confirm operating system, Python version, install method, and whether a virtual environment is active.
- Ask for the exact command, sanitized config path, and sanitized output path.
- Ask whether the input was CSV or XLSX, and which export-based ERP profile or control pack was used.
- Ask for the full safe error message shown by the CLI, not a raw traceback unless it is already sanitized.
- Ask for synthetic, anonymized, or header-only sample files when reproduction data is needed.
- Ask whether the user ran `reconforge doctor`, `reconforge validate`, the 10-minute demo, or the synthetic enterprise demo.
- Ask whether the issue touches file handling, generated HTML, evidence, client packs, YAML loading, Studio routes, DB import/export, backup, or mapping validation.

## Severity Levels

| Severity | Draft meaning | Examples |
| --- | --- | --- |
| S1 Critical | Local data safety or integrity risk in a supported workflow. | Path traversal, unsafe HTML output, corrupted generated evidence manifest, credential exposure. |
| S2 High | A core local workflow is blocked for a pilot or release gate. | Management pack command fails on valid sanitized exports, DB backup verification fails, mapping validation crashes. |
| S3 Normal | Important usability, docs, mapping, or control behavior issue. | Ambiguous buyer docs, confusing setup step, missing safe error text, rule-pack validation gap. |
| S4 Low | Clarification, enhancement request, typo, or future planning item. | Suggested example, wording improvement, new export profile request. |

## Draft Response Targets

These examples are draft and non-contractual. They are planning aids only and do not guarantee response or resolution.

| Severity | Draft first-response target | Draft update rhythm |
| --- | --- | --- |
| S1 Critical | 1 business day when maintainers are available. | Daily while actively triaged. |
| S2 High | 2 business days when maintainers are available. | Every 2 to 3 business days while active. |
| S3 Normal | 5 business days when maintainers are available. | As maintainers have capacity. |
| S4 Low | Best effort. | No fixed update rhythm. |

## What Users Should Provide

- ReconForge version or commit.
- Operating system, Python version, and install command.
- Exact command run and sanitized paths.
- Sanitized config and control-pack names.
- Header-only CSV/XLSX examples or synthetic/anonymized samples.
- Expected behavior and observed behavior.
- Generated output filenames, with sensitive values redacted.
- Whether the issue is public, private pilot feedback, security-sensitive, or a documentation request.

## What Users Should Not Share

- Live customer data or real ERP exports in public issues.
- Passwords, API keys, tokens, SSH keys, database credentials, or session values.
- Customer, supplier, employee, bank, payroll, tax, invoice, GL, asset, or financial statement records.
- Unredacted evidence binders, client packs, backups, or SQLite databases from real environments.
- Screenshots showing private entity names, balances, emails, IDs, or document numbers.

Use synthetic data, anonymized exports, or the generated enterprise demo package for public troubleshooting. If a private support arrangement exists, data-sharing rules should be written down separately and approved by the data owner.

## Escalation Guidance

- Escalate possible security issues to the security process in `SECURITY.md`.
- Escalate data exposure, path traversal, unsafe HTML, unsafe archive behavior, unsafe YAML handling, or secret leakage as S1 until assessed.
- Escalate release-blocking failures in required quality gates as S2.
- Escalate unclear buyer, compliance, or audit wording when it could imply unsupported claims.
- Keep escalation notes factual: what failed, how it was reproduced, what data was used, and which checks passed.

## Known Limitations

- ReconForge is early-stage and pilot-ready, not enterprise production software.
- Core workflows are local-first and export-based; there are no direct ERP connectors.
- There is no SaaS support desk, hosted tenant, telemetry service, or cloud upload workflow.
- There is no guaranteed SLA.
- Docker runtime verification is only claimed after documented build/run commands pass in a real Docker environment.
- Evidence checksums are integrity aids only, not legal signatures or non-repudiation.
- Review and certification metadata supports workflow tracking only; it does not create audit opinions or compliance certification.

## No SLA Guarantee

Open-source issue triage and any draft response targets are best-effort unless a separate written agreement exists. This playbook does not create a service-level agreement, warranty, legal assurance, audit opinion, compliance certification, or incident-response commitment.
