# Maintainer Triage Guide

Use this guide to handle GitHub Issues, Discussions, PRs, and external feedback consistently.

## First Pass

1. Confirm the report does not include live ERP data, customer names, employee data, GL details, invoices, credentials, or private financial values.
2. Add labels from `docs/maintainers/labels.md`.
3. Identify whether the issue is a bug, docs request, export-profile request, rule-pack request, security report, pilot feedback, or feature proposal.
4. Ask for sanitized headers, synthetic rows, commands, and expected behavior when reproduction details are missing.

## Security Issues

Do not ask reporters to publish exploit details or sensitive data in public issues. If a report suggests path traversal, raw exception leakage, XSS, unsafe YAML parsing, direct file serving, dependency compromise, or private data exposure:

- move discussion to the private security process described in `SECURITY.md`
- request synthetic reproduction steps only
- avoid confirming exploitability publicly before a fix is available
- add regression tests after remediation
- update security docs if the threat model or mitigation changes

## Feature Requests

Evaluate feature requests against these questions:

- Does it preserve local-first processing?
- Can it work from CSV/XLSX exports without live ERP credentials?
- Does it strengthen reconciliation, evidence, mapping, review, docs, tests, or maintainability?
- Is the requested behavior a small workflow improvement rather than feature bloat?
- Can the acceptance criteria be tested with synthetic or anonymized data?

Decline or defer requests for SaaS, cloud upload, telemetry, live ERP credential handling, production compliance claims, or broad platform expansion.

## Avoiding Overclaims

When editing titles, labels, comments, docs, or release notes, avoid wording that implies:

- customer adoption
- production enterprise readiness
- audit opinions or assurance conclusions
- legal, tax, regulatory, or compliance certification
- direct ERP connectors
- signed artifacts
- Docker runtime verification without passing evidence

Use factual wording tied to implemented behavior.

## Closing Duplicates

Close duplicates only after linking the original issue and confirming the scope matches. If the duplicate includes new synthetic data, sanitized headers, or acceptance criteria, copy that context into the active issue before closing.

## Prioritizing Roadmap

Prioritize:

1. security fixes and private data safety
2. regressions in CLI, Studio, reports, evidence, review workflow, redaction, or mapping validation
3. tests that protect existing workflows
4. export-profile and rule-pack improvements with clear practitioner value
5. docs that help users run local workflows safely
6. automation that improves release and maintainer reliability

Defer broad product features until they have a clear local-first implementation path and testable acceptance criteria.
