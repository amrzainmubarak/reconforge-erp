# OSS Support Application Notes

These notes provide reusable, conservative wording for open-source support, maintainer funding, and AI assistance applications.

## Project Summary

ReconForge ERP is an early-stage, local-first, export-based ERP reconciliation toolkit. It helps finance, audit, ERP, inventory, workshop, fleet, and SME teams review stock-to-GL matching, WIP/work-order controls, rule-pack exceptions, evidence binders, and client handoff outputs from local CSV/XLSX exports.

The project does not require cloud upload or direct ERP connectors for core workflows.

## Maintainer Role

The maintainer is responsible for:

- preserving local-first architecture
- reviewing rule packs and ERP export profiles
- maintaining tests, docs, CI, security workflows, and releases
- preventing overclaims about adoption, compliance, direct connectors, or production readiness
- supporting contributors who bring finance, audit, ERP, and operations expertise

## Why The Repo Matters

ERP reconciliation and audit evidence work is often closed, expensive, spreadsheet-heavy, or cloud-dependent. ReconForge ERP provides inspectable controls, reusable export profiles, synthetic demos, and local evidence preparation for sensitive ERP data.

## Current Maturity

Current repository proof points include:

- v0.6.1 - Pilot Readiness Hardening
- 150 passing tests in the current validation state
- CI, CodeQL, Bandit, Ruff, mypy, pytest, and dependency security workflows
- export-based profiles for Odoo, SAP, ERPNext, Dynamics, and NetSuite scenarios
- review workflow, evidence integrity manifests, redaction controls, and client handoff pack docs
- conservative security, privacy, compliance, onboarding, and release documentation

These proof points should not be described as customer adoption.

## How AI And Codex Help

AI assistance would be useful for:

- PR review and security review
- generating focused tests for rule packs, mapping profiles, and report edge cases
- reviewing docs for overclaims
- maintaining release checklists
- triaging issues and suggested good-first tasks
- improving accessibility and demo workflows
- checking generated HTML, path handling, and YAML safety regressions

AI output should be human-reviewed before merge.

## Security Needs

Priority security needs:

- continued path traversal hardening
- generated HTML escaping and href quoting review
- dependency scanning and SBOM generation
- OpenSSF Scorecard review
- safer demo output sharing guidance
- stronger redaction and workbook handling over time

Security tooling is supportive evidence, not certification.

## API Credits Usage

Potential AI/API credit usage:

- automated PR review summaries
- targeted test generation
- rule-pack review and documentation drafting
- export-profile mapping review from sanitized headers
- release note consistency checks
- security hardening review prompts

No private ERP exports should be sent to an AI provider without explicit user approval and an appropriate data policy.

## Limitations To Disclose

- New project with limited external adoption documented.
- No real customer claims.
- No direct ERP connectors.
- No legal, tax, audit, or compliance certification.
- Docker runtime verification should only be claimed after documented build and run commands pass.
- Evidence manifests provide checksums, not legal digital signatures.

## Updated Metrics To Track

- release version
- test count and passing status
- CI/security workflow status
- number of rule packs
- number of export profiles
- open/closed issues by category
- external feedback received through public issues or discussions
- Scorecard results after workflow runs
- SBOM artifact availability after tagged releases

## Careful Wording

Use:

- "local-first"
- "export-based"
- "pilot-ready open-source toolkit"
- "evidence preparation"
- "integrity aid"
- "early-stage"

Avoid:

- "customer-proven"
- "certified"
- "audit opinion"
- "production-ready enterprise platform"
- "direct connector"
- "guaranteed compliant"
