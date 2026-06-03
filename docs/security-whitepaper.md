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

## 5. YAML Rule Safety Model

Control packs are YAML configuration, not arbitrary executable Python. Rules are loaded into pydantic models and evaluated through supported operators. Mapping validation checks required pack files, YAML structure, rule IDs, severities, supported operators, and schema conformance.

Known limitation: YAML rules can still encode poor business logic. They must be reviewed before use in client work.

## 6. Download Route Safety

Dashboard and Studio download routes use registry-based allowlists. The app builds a list of allowed local files and serves only registered keys with allowed suffixes. Route parameters are not directly joined to filesystem paths.

## 7. HTML Escaping And XSS Controls

Static HTML reports and Studio pages escape rendered values before inserting them into HTML. Studio review fields such as reviewer and note are escaped when displayed. Tests cover table escaping and review-action escaping.

Known limitation: generated HTML files are static local artifacts. Users should still treat generated output as sensitive and open it in trusted contexts.

## 8. Path Traversal Protections

Download keys reject absolute paths, Windows drive prefixes, backslashes, parent traversal markers, empty path segments, and unsupported suffixes. Tests cover dashboard and Studio traversal attempts.

## 9. Dependency And Security Scanning

The repository includes quality gates for:

- Ruff
- mypy
- pytest
- Bandit
- CodeQL
- package build

Dependency review should be performed before production use. `pip-audit` is listed in development dependencies.

## 10. CodeQL And Bandit

CodeQL and Bandit are part of the intended security workflow. Passing these tools reduces common static-analysis risk but is not equivalent to a penetration test, formal secure-code audit, or compliance certification.

## 11. Review Workflow Data Storage

Review state is stored in `output/review_state.json`. It contains exception IDs, status, reviewer, note, decision reason, accepted-risk reason, escalation owner, and timestamps. There is no database and no authentication layer.

Known limitation: users who can write to the output folder can modify review state.

## 12. Evidence Binder Privacy Considerations

Evidence folders may include source-record extracts, match candidates, triggered rules, recommended actions, and audit-trail JSON. These outputs are useful for review, but they may contain sensitive names, identifiers, and monetary values.

Client handoff packs include a privacy note and manifest. Teams must review evidence before external sharing.

## 13. Docker Deployment Considerations

The Dockerfile packages the local CLI and repository assets. Docker does not add authentication, encryption, or approval workflows. Mounted host directories remain governed by host permissions.

Recommended practice:

- mount only required input/output folders
- avoid broad home-directory mounts
- keep generated outputs in controlled local paths
- review evidence before sharing

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

## 16. Security Roadmap

Near-term:

- stronger client-pack exclusion controls
- optional output redaction checklist
- Docker build verification in CI if lightweight
- dependency audit workflow hardening
- clearer secure deployment defaults

Longer-term:

- authenticated local workspace mode
- signed evidence bundles
- role-aware review workflow
- optional encrypted local state
- connector-specific credential threat models if direct connectors are implemented

## 17. Responsible Disclosure

Report suspected vulnerabilities using the process in `SECURITY.md`. Do not include sensitive client ERP data in public reports or issue trackers.
