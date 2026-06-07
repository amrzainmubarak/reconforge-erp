# ReconForge ERP Security Whitepaper

ReconForge ERP is designed as a local-first, export-based reconciliation and audit intelligence tool. This document explains the current security posture, data flow, controls, limitations, and roadmap for pilot evaluation.

## 1. Local-First Architecture

Core workflows run on local files. Users provide CSV/XLSX exports, run CLI commands, and generate reports under local output folders. The project does not require a SaaS tenant, hosted database, or paid API for reconciliation, rules, reports, evidence binder, Studio review actions, or demo workflows.

## 2. No Cloud Upload By Default

ReconForge does not upload ERP exports by default. Generated reports, review state, mapping reports, comparison outputs, and evidence binder files are written to local paths.

Users remain responsible for any sharing they perform outside ReconForge, such as sending a client pack by email or uploading outputs to another system.

## 3. Data Flow

1. Local ERP exports are placed in an input folder.
2. ReconForge validates schemas and reads required datasets.
3. Reconciliation, rules, WIP aging, and risk scoring run locally.
4. Reports are written as Excel, HTML, Markdown, CSV, and JSON.
5. Evidence binder folders are generated for high and critical exceptions.
6. Review state is written to `review_state.json`.
7. Optional client packs copy selected generated artifacts into a local handoff folder.

## 4. File Input Handling

ReconForge reads CSV/XLSX files from paths supplied by the user. Input validation checks required fields, references, and basic data quality. The mapping wizard reads lightweight header samples and handles malformed CSVs by reporting errors rather than modifying files.

## 4.1 Data Classification Guidance

Before a pilot, classify exports and outputs at least as:

- public demo or synthetic
- internal business data
- confidential ERP data
- restricted personal, customer, supplier, employee, equipment, or financial data

Client packs and evidence binders should be treated as confidential until reviewed and approved for sharing.

## 5. YAML Rule Safety Model

Control packs are YAML configuration, not arbitrary executable Python. Rules are loaded into pydantic models and evaluated through supported operators. Mapping validation checks required pack files, YAML structure, rule IDs, severities, supported operators, and schema conformance.

Known limitation: YAML rules can still encode poor business logic. They must be reviewed before use in client work.

## 6. Download Route Safety

Dashboard and Studio download routes use registry-based allowlists. The app builds a list of allowed local files and serves only registered keys with allowed suffixes. Route parameters are not directly joined to filesystem paths.

## 7. HTML Escaping And XSS Controls

Static HTML reports and Studio pages escape rendered values before inserting them into HTML. Studio review fields such as reviewer and note are escaped when displayed. Tests cover table escaping and review-action escaping.

Known limitation: generated HTML files are static local artifacts. Users should still treat generated output as sensitive and open it in trusted contexts.

Studio review-status errors use static user-facing messages for invalid status values. Raw exception internals and raw user input are not rendered into the invalid-status response.

## 8. Path Traversal Protections

Download keys reject absolute paths, Windows drive prefixes, backslashes, parent traversal markers, empty path segments, and unsupported suffixes. Tests cover dashboard and Studio traversal attempts.

## 9. Dependency And Security Scanning

The repository includes quality gates for:

- Ruff
- mypy
- pytest
- Bandit
- CodeQL
- OpenSSF Scorecard
- CycloneDX SBOM generation
- package build

Dependency review should be performed before production use. `pip-audit` is listed in development dependencies.

OpenSSF Scorecard is configured as a scheduled/manual repository security maturity check. It should be used to prioritize improvements, not as a guarantee that the repository is secure.

The SBOM workflow generates a CycloneDX Python dependency artifact on release tags and manual dispatch. This improves dependency visibility, but it is not artifact signing, legal assurance, or supply-chain certification.

## 10. CodeQL And Bandit

CodeQL and Bandit are part of the intended security workflow. Passing these tools reduces common static-analysis risk but is not equivalent to a penetration test, formal secure-code audit, or compliance certification.

## 11. Review Workflow Data Storage

Review state is stored in `output/review_state.json`. It contains exception IDs, status, reviewer, note, decision reason, accepted-risk reason, escalation owner, and timestamps. There is no database and no authentication layer.

Known limitation: users who can write to the output folder can modify review state.

## 12. Evidence Binder Privacy Considerations

Evidence folders may include source-record extracts, match candidates, triggered rules, recommended actions, and audit-trail JSON. These outputs are useful for review, but they may contain sensitive names, identifiers, and monetary values.

Client handoff packs include a privacy note and manifest. Teams must review evidence before external sharing.

Evidence binders now write `evidence_manifest.json` with SHA-256 checksums. This is an integrity aid, not a legal digital signature.

Client packs support redaction and exclusion options:

- `--redact-names`
- `--redact-amounts`
- `--exclude-raw-records`
- `--summary-only`
- `--exclude-evidence`
- `--include-manifest-checksums`

Redaction applies only to copied client-pack files. Binary workbooks are excluded when redaction is requested because text-level redaction cannot safely rewrite every workbook cell.

## 13. Docker Deployment Considerations

The Dockerfile packages the local CLI and repository assets. Docker does not add authentication, encryption, or approval workflows. Mounted host directories remain governed by host permissions.

Recommended practice:

- mount only required input/output folders
- avoid broad home-directory mounts
- keep generated outputs in controlled local paths
- review evidence before sharing

ReconForge ERP v0.7.0 includes Docker build workflow support and deployment documentation. Docker runtime verification is not claimed unless the documented build and run commands pass in a live Docker environment. See `docs/docker-verification.md`.

## 14. Threat Model

Primary threats considered:

- accidental sharing of sensitive ERP outputs
- path traversal in local download routes
- XSS through rendered exception or reviewer fields
- malformed or incomplete input files
- unsafe YAML logic or unsupported rule operators
- dependency vulnerabilities
- local unauthorized access to output folders

Out of scope for the current local-first version:

- hosted multi-user access control
- SSO
- network perimeter controls
- database security
- live ERP credential handling
- regulated audit-opinion workflow

## 15. Known Limitations

- No authentication in Studio or dashboard.
- No role-based access control.
- No encrypted review-state store.
- No direct ERP connector security model.
- No third-party security certification.
- No formal data retention policy beyond local files.
- No automatic PII classification in outputs.
- No workbook-level redaction when redaction is requested; binary workbooks are excluded from redacted client packs.
- No legal digital signature for evidence bundles; only checksums are currently implemented.

## 16. Security Roadmap

Near-term:

- authenticated local workspace mode
- workbook-level redaction strategy or clearer safe-export alternatives
- Docker runtime verification across supported local environments
- dependency audit workflow hardening
- Scorecard finding review and remediation process
- SBOM artifact review for tagged releases
- clearer secure deployment defaults
- signed release artifact investigation

Longer-term:

- signed evidence bundles
- role-aware review workflow
- optional encrypted local state
- credential-handling threat models if live ERP integrations are ever implemented

## 17. Responsible Disclosure

Report suspected vulnerabilities using the process in `SECURITY.md`. Do not include sensitive client ERP data in public reports or issue trackers.
