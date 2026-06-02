# Product Roadmap

This roadmap keeps the core local-first, deterministic, export-based, and audit-friendly. Versions are planning targets, not adoption claims.

## v0.4.0 - ERP Mapping Foundation

| Area | Plan |
| --- | --- |
| Features | Rule-pack schema reference; Odoo stock valuation mapping profile; SAP MB51/FAGLL03 mapping profile; better control-pack docs; more realistic sample export guidance; demo workflow for Odoo and SAP users. |
| Why it matters | Users need to know how exports become canonical ReconForge files before they can trust reconciliation results. |
| Required files | `docs/rule-pack-schema-reference.md`, `control-packs/odoo-inventory-valuation/*`, `control-packs/sap-mb51-fagll03/*`, `docs/odoo-export-guide.md`, `docs/sap-export-guide.md`, README, changelog, structure tests. |
| CLI commands | `reconforge rules validate --pack control-packs/odoo-inventory-valuation`; `reconforge rules run --input examples/sample_data --pack control-packs/odoo-inventory-valuation --output output/rules-odoo`; `reconforge rules validate --pack control-packs/sap-mb51-fagll03`; `reconforge reconcile stock-gl --input examples/sample_data --config config/reconforge.yml --output output`. |
| Tests | Docs presence; Odoo/SAP pack structure; mapping keys; valid YAML; pack loading; sample command and expected exceptions present. |
| Docs | Rule schema reference; Odoo and SAP export guides; pack READMEs; expected exceptions; sample commands. |
| Acceptance criteria | A new user can identify required Odoo/SAP exports, map fields into canonical CSVs, validate packs, run rules, and understand expected exceptions without cloud upload. |
| Release notes draft | Adds the ERP mapping foundation for v0.4.0 with rule-pack schema documentation and stronger Odoo/SAP export-based mapping profiles. |

## v0.5.0 - Review Workflow And Studio Upgrade

| Area | Plan |
| --- | --- |
| Features | Evidence reviewer status workflow; exception lifecycle values: New, Under Review, Resolved, Accepted Risk, Escalated; Studio filters; reviewer notes; evidence register improvements; local review state file. |
| Why it matters | Exceptions need ownership, review decisions, notes, and status history before teams can use ReconForge in a close process. |
| Required files | `reconforge/review/`, `reconforge/studio/app.py`, `reconforge/evidence/binder.py`, evidence register writer, CLI review commands, tests. |
| CLI commands | `reconforge review init --output output/review_state.yml`; `reconforge review update --exception-id EXC-0001 --status under-review --note "Investigating"`; `reconforge studio --input examples/sample_data --output output`. |
| Tests | State file creation; valid/invalid status transitions; evidence register includes status and reviewer notes; Studio filter smoke tests; CLI update tests. |
| Docs | Review workflow guide; Studio guide update; evidence binder guide update; reviewer status reference. |
| Acceptance criteria | A reviewer can assign status and notes locally, reopen Studio, and see persisted review state reflected in evidence outputs. |
| Release notes draft | Adds local exception review workflow and Studio filtering so evidence review can move beyond static reports. |

## v0.6.0 - Multi-Period Intelligence

| Area | Plan |
| --- | --- |
| Features | Compare periods; recurring exceptions; new/resolved exceptions; exception aging; trend reporting; month-end close pack. |
| Why it matters | Controllers and auditors need to know whether issues are new, aging, recurring, or resolved across closes. |
| Required files | `reconforge/periods/`, comparison models, report writers, close pack generator, tests, sample period datasets. |
| CLI commands | `reconforge compare periods --previous output/2026-04 --current output/2026-05 --output output/period-compare`; `reconforge report close-pack --input output/period-compare --output output/close-pack`. |
| Tests | Stable exception fingerprinting; new/resolved/recurring classification; aging buckets; trend output; close pack artifacts. |
| Docs | Multi-period guide; close-pack guide; exception fingerprinting reference. |
| Acceptance criteria | Two period outputs can be compared deterministically and produce new/resolved/recurring/aging reports. |
| Release notes draft | Adds multi-period intelligence for recurring exceptions, trend reporting, and month-end close evidence packs. |

## v0.7.0 - ERP Ecosystem Expansion

| Area | Plan |
| --- | --- |
| Features | ERPNext CSV profile; Microsoft Dynamics CSV profile; NetSuite CSV profile; manufacturing variance examples; 10k and 100k benchmark datasets. |
| Why it matters | The category becomes credible only if ReconForge is not limited to one ERP export pattern. |
| Required files | New control packs and mapping profiles; benchmark dataset generation configs; docs; tests. |
| CLI commands | `reconforge rules validate --pack control-packs/erpnext-inventory`; `reconforge generate synthetic --rows 100000 --industry manufacturing --output benchmarks/manufacturing_100k`; `reconforge benchmark --input benchmarks/manufacturing_100k --engine pandas --output output/benchmark-100k`. |
| Tests | Pack structure; mapping required keys; benchmark generation; rules load; performance smoke tests. |
| Docs | ERPNext, Dynamics, NetSuite export guides; manufacturing variance examples; benchmark report. |
| Acceptance criteria | Each new ERP profile has practical mapping docs, valid rules, sample commands, and tests. Benchmark artifacts are reproducible. |
| Release notes draft | Expands ERP profile coverage and introduces larger benchmark datasets for realistic performance review. |

## v0.8.0 - Consultant Toolkit

| Area | Plan |
| --- | --- |
| Features | Mapping wizard; anonymized customer demo package generator; report branding; client handoff pack; implementation playbooks; training materials. |
| Why it matters | Consultants need repeatable delivery assets, not just a CLI. |
| Required files | `reconforge/mapping/`, `reconforge/handoff/`, branding config, playbooks, training docs, tests. |
| CLI commands | `reconforge mapping wizard --input client_exports --profile odoo-inventory-valuation --output mapped_exports`; `reconforge handoff pack --input output --brand config/client_brand.yml --output output/client-handoff`. |
| Tests | Mapping wizard dry-run; anonymized package generation; branding config validation; handoff pack artifact checks. |
| Docs | Consultant implementation guide; handoff pack guide; training outline; mapping wizard reference. |
| Acceptance criteria | A consultant can prepare a client-safe demo and handoff pack without writing custom code. |
| Release notes draft | Adds consultant delivery workflows for mapping, anonymized demos, branded reports, handoff packs, and training. |

## v0.9.0 - Self-Hosted Review Platform Foundation

| Area | Plan |
| --- | --- |
| Features | Local authentication option; reviewer roles; persistent local SQLite state; saved review sessions; exportable audit review pack; Docker Compose local deployment. |
| Why it matters | Teams need local collaboration without turning the core into cloud software. |
| Required files | Auth module, SQLite models, review API, Studio views, Docker Compose updates, security docs, tests. |
| CLI commands | `reconforge review serve --input output --state reconforge_state.db`; `docker compose up`. |
| Tests | Auth flow; role permissions; SQLite persistence; saved sessions; export review pack; local deployment smoke. |
| Docs | Self-hosted review guide; local auth model; Docker Compose guide; security model update. |
| Acceptance criteria | A local/self-hosted team can review exceptions with roles and persistent state, then export an audit review pack. |
| Release notes draft | Introduces the self-hosted review platform foundation with local auth, roles, SQLite state, and saved sessions. |

## v1.0.0 - Stable Open-Source Core

| Area | Plan |
| --- | --- |
| Features | Stable CLI; stable schemas; stable control-pack format; stable evidence binder format; stable plugin interface; production-ready docs; migration guide; security model; community governance. |
| Why it matters | v1.0.0 should be the point where users can build repeatable processes and contributors can extend the project with predictable contracts. |
| Required files | Versioned schema docs; migration guide; governance docs; release checklist; plugin API docs; security model; compatibility tests. |
| CLI commands | Existing stable commands plus `reconforge schema validate`, `reconforge mapping validate`, and migration helpers if needed. |
| Tests | Backward compatibility fixtures; CLI contract tests; schema validation tests; plugin interface tests; evidence format tests; migration tests. |
| Docs | Production guide; governance; migration guide; stable schema reference; security and privacy docs; contributor guide refresh. |
| Acceptance criteria | Users can rely on documented stable formats, migration guidance, tested CLI behavior, and governance for official/community packs. |
| Release notes draft | Stabilizes the open-source core with versioned schemas, stable control-pack and evidence formats, plugin contracts, production docs, and governance. |
