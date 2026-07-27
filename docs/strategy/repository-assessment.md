# Repository Assessment

Assessment date: 2026-06-02

Scope inspected: `README.md`, `CHANGELOG.md`, `docs/roadmap.md`, `SECURITY.md`, `CONTRIBUTING.md`, `.github/`, `reconforge/`, `tests/`, `docs/`, `examples/`, and `control-packs/`.

## Summary

ReconForge ERP is a credible early-stage local-first reconciliation project. It has working CLI workflows, deterministic rule execution, report generation, evidence binder outputs, anonymization, synthetic data, benchmarking, a local Studio, control packs, CI, CodeQL, Bandit, and practical docs. That is stronger than a typical alpha project.

The main gap is not ambition. The gap is product hardness. ERP mapping profiles are still mostly documentation and YAML guidance, not a validated mapping layer. Review workflow state is not yet persistent. Multi-period intelligence is absent. Commercial pilot readiness is limited by missing implementation playbooks, stable schemas, migration policy, review roles, and repeatable customer onboarding assets.

## Current Strengths

1. Local-first posture is clear in README, security docs, and implementation defaults.
2. CLI is broad enough for a real workflow: validation, reconciliation, rules, reports, evidence, anonymization, synthetic data, benchmarks, Studio, and doctor checks.
3. Stock-to-GL and work-order reconciliation are implemented, not just described.
4. Rule engine is deterministic, YAML-based, Pydantic-validated, and operator-limited.
5. Evidence binder creates useful local case artifacts and an evidence register.
6. Control-pack structure is already consistent across 15 packs.
7. Sample and anonymized datasets exist across operational and accounting files.
8. Synthetic data and benchmarking give the project a path to measurable claims.
9. Tests cover reconciliation, validation, rules, evidence, anonymization, Studio, safe paths, and v0.3 platform features.
10. CI covers Ruff, mypy, pytest, CLI smoke checks, and package build across Python 3.11 and 3.12.
11. Security workflows include CodeQL, Bandit, pip-audit, Dependabot, and a security policy.
12. README has real screenshots and avoids fake adoption claims.
13. Documentation already targets ERP, audit, privacy, architecture, playbooks, and launch needs.
14. Plugin/connector foundation separates export adapters from core reconciliation.
15. The project has a plausible niche: export-based operational reconciliation where enterprise close tools are too heavy and spreadsheets are too fragile.

## Current Weaknesses

1. Mapping profiles are not yet validated by the CLI.
2. There is no first-class command that transforms raw Odoo, SAP, ERPNext, NetSuite, or Dynamics exports into the canonical ReconForge schema.
3. The Odoo and SAP packs existed before v0.4.0 work, but were thin compared with the strategic importance of those ecosystems.
4. Rule-pack schema documentation was missing before this pass.
5. No persistent exception lifecycle exists yet.
6. Studio is not yet a serious reviewer workflow.
7. Multi-period comparison, recurring exceptions, aging, and close-pack generation are not implemented.
8. There is no stable schema versioning policy or migration guide.
9. The evidence binder does not yet support durable reviewer ownership, status, sign-off, attachments, or local role enforcement.
10. Commercial pilot readiness is mostly strategic, not operational.
11. No package-published adoption evidence is present in the repo.
12. No external contributor loop is visible beyond general contribution docs.
13. Good-first-issue structure is not yet operationalized in the repository state.
14. Benchmarks exist, but not yet 10k/100k datasets with published benchmark results.
15. No signed releases, SBOM, or explicit supply-chain attestation workflow is present.
16. No formal threat model document existed before the v0.4.0 strategy work.
17. The plugin security policy is not yet enforceable through interfaces or tests.
18. The README still has a broad capability list; the category wedge needs to be more visible.
19. There is no consultant handoff pack or implementation checklist suitable for a paid pilot.
20. Documentation is broad but not yet organized into a tight user journey for Odoo/SAP users.

## Maturity Scores

Scores are 1 to 10 and reflect current repository evidence, not aspirations.

| Area | Score | Rationale |
| --- | ---: | --- |
| Technical maturity | 6.5 | Working workflows, tests, typed Python, CLI, reports, and rules exist. Mapping, review state, schema stability, and multi-period intelligence are still immature. |
| Security maturity | 6.5 | Local-first posture, safe-path tests, CodeQL, Bandit, pip-audit, Dependabot, and guidance are strong for alpha. Missing SBOM, signed releases, deeper threat modeling, plugin policy enforcement, and secure review checklists. |
| Documentation maturity | 7.0 | Broad documentation and real screenshots exist. Missing schema reference before v0.4.0 and user journeys need more focus. |
| Product clarity | 6.0 | The category is plausible, but the user path from ERP export to mapped canonical files needs clearer commands, examples, and boundaries. |
| Open-source readiness | 6.5 | License, contributing, security, issue templates, CI, docs, examples, and control packs exist. Needs labels, contribution ladder, good-first issues, governance, and release discipline. |
| Commercial readiness | 4.0 | Strong foundations, but pilots need stable schemas, onboarding assets, review workflow, support boundaries, implementation playbooks, and partner-facing materials. |

## Missing Foundations

1. Validated `mapping.yml` schema.
2. Mapping command or wizard for export-to-canonical transformation.
3. Stable schema versioning and compatibility policy.
4. Durable local review state.
5. Exception lifecycle and reviewer workflow.
6. Multi-period comparison engine.
7. Published benchmark datasets and reproducible benchmark report.
8. Consultant implementation pack.
9. Security threat model and plugin policy.
10. External contribution issue backlog.
11. Release checklist with migration and security gates.
12. Governance model for maintainers, rule packs, and accepted mappings.
13. Odoo/SAP demo workflow with realistic field-level mapping.
14. Commercial pilot checklist and success criteria.
15. Documentation IA that separates accountant, auditor, consultant, and engineer paths.

## Top 20 Improvements Ranked By Strategic Impact

1. Add validated ERP mapping profiles and a mapping CLI.
2. Implement Odoo stock valuation layer to canonical schema transformation.
3. Implement SAP MB51/FAGLL03/FBL3N export mapping workflow.
4. Add persistent local exception lifecycle state.
5. Add multi-period exception comparison and aging.
6. Publish 10k and 100k benchmark datasets and results.
7. Define stable rule-pack, evidence binder, and canonical data schemas.
8. Add reviewer roles and local review sessions.
9. Add consultant handoff pack generator.
10. Add implementation playbooks for Odoo and SAP consultants.
11. Add a formal threat model and secure plugin policy.
12. Add migration guides for schema/control-pack changes.
13. Improve Studio filters, drilldowns, notes, and evidence links.
14. Add ERPNext, Dynamics, and NetSuite CSV profiles.
15. Create training materials for contributors and consultants.
16. Add signed releases and SBOM generation.
17. Add issue labels and starter issues for mappings and controls.
18. Add report branding and client handoff outputs.
19. Build a feedback loop for anonymized real-world scenarios.
20. Create governance rules for official and community control packs.

## Top 20 Improvements Ranked By Speed Of Execution

1. Add rule-pack schema reference.
2. Expand Odoo mapping profile docs.
3. Expand SAP mapping profile docs.
4. Add tests for Odoo/SAP pack structure.
5. Add README section for ERP mapping profiles.
6. Add v0.4.0 changelog notes.
7. Add mapping-profile issue template.
8. Add control-pack issue template.
9. Add rule-pack contributor checklist.
10. Add sample command files with full demo sequence.
11. Add expected exception docs for Odoo/SAP.
12. Add source field mapping tables in export guides.
13. Add recommended labels list to adoption docs.
14. Add release checklist to maintainer docs.
15. Add benchmark targets to roadmap.
16. Add explicit "no cloud upload" wording near ERP profiles.
17. Add docs index links for strategy artifacts.
18. Add security PR checklist.
19. Add Odoo/SAP workflow diagrams or tables.
20. Add examples of invalid rule YAML.

## Required Before Serious Community Growth

1. A concise contributor journey: install, run sample, add a rule, validate pack, open PR.
2. Good-first issues that do not require private ERP knowledge.
3. Clear labels for mapping, rule pack, docs, tests, security, Odoo, SAP, and Studio work.
4. Rule-pack schema reference and mapping-profile examples.
5. No fake adoption language.
6. A public roadmap that distinguishes implemented, planned, and experimental capabilities.
7. Better docs navigation by persona.
8. A maintainer response model for issues and pull requests.
9. A policy for accepting community control packs.
10. A policy for anonymized sample data submissions.

## Required Before Commercial Pilots

1. Stable canonical schema for pilot scope.
2. Stable rule-pack and evidence binder formats for pilot scope.
3. Odoo/SAP implementation playbooks.
4. A pilot kickoff checklist and data intake checklist.
5. A local deployment guide for locked-down finance environments.
6. Pilot acceptance criteria: data mapped, exceptions reviewed, evidence pack generated, handoff completed.
7. Security review checklist for customer environments.
8. Support scope and response expectations.
9. Report branding and client handoff pack.
10. A commercial boundary that keeps core reconciliation, rule packs, anonymization, and evidence generation open.

## Bottom Line

ReconForge ERP has a plausible path to becoming a trusted open-source option for local-first ERP audit intelligence if it narrows the wedge, hardens mapping, and turns docs into repeatable adoption workflows. It is not ready to claim category leadership. It is ready to build the foundations that could make stronger claims evidence-based later.
