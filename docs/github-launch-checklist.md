# GitHub Launch Checklist

## Repository Name

Recommended repository name: `reconforge-erp`

If the local folder still has spaces, rename it after closing active terminals:

```bash
mv "ReconForge ERP" reconforge-erp
```

## Repository Description

Open-source ERP reconciliation and audit intelligence for stock movements, GL entries, work orders, WIP, invoices, purchase flows, and operational controls.

## Recommended Topics

- `erp`
- `odoo`
- `sap`
- `accounting`
- `finance`
- `reconciliation`
- `audit`
- `inventory`
- `wip`
- `internal-controls`
- `stock-management`
- `financial-close`
- `python`
- `open-source`
- `cli`
- `fastapi`
- `duckdb`

## Social Preview Idea

Use a clean local screenshot of the management pack summary or ReconForge Studio dashboard with the text: “The open-source audit layer between inventory operations and financial accounting.”

## First Release Checklist

- Confirm `ruff check .`, `mypy reconforge`, and `pytest` pass.
- Generate demo outputs from sample data.
- Confirm Docker build where Docker is available.
- Review README, SECURITY, CONTRIBUTING, and ROADMAP.
- Ensure sample data is synthetic and safe.
- Publish v0.2.0 release notes.
- Open initial issues with clear scope.

## First 20 GitHub Issues to Open

1. Add Odoo stock valuation export mapping template.
2. Add SAP MB51 to canonical schema mapping guide with screenshots.
3. Add exception review status fields to evidence binder output.
4. Add benchmark profile for 10k generated rows.
5. Add recurring-equipment repair rule to fleet control pack.
6. Add reviewer assignment view in ReconForge Studio.
7. Add ERPNext mapping profile.
8. Add NetSuite inventory adjustment mapping profile.
9. Add configurable duplicate-reference rule support.
10. Add report screenshots generated from local sample outputs.
11. Add Dynamics 365 CSV mapping profile.
12. Add recurring-period comparison report.
13. Add Studio risk-level filter UI.
14. Add evidence binder reviewer status export.
15. Add rule-pack schema documentation.
16. Add control-pack contribution checklist.
17. Add synthetic dealership warranty scenarios.
18. Add manufacturing variance examples.
19. Add DuckDB benchmark comparison when optional dependency is installed.
20. Add first social preview image from local generated reports.

## First 10 Good-First-Issues

1. Add README links to one playbook.
2. Add a missing interpretation example to a control pack README.
3. Add one test for a rule operator.
4. Add one synthetic data scenario label.
5. Improve an evidence binder Markdown heading.
6. Add docs for one sample output file.
7. Add a small CLI smoke test.
8. Add a glossary term to the plain-English guide.
9. Add Arabic translation for one short section.
10. Add a report preview table row.

## First 10 Help-Wanted Issues

1. Odoo stock valuation mapping profile.
2. SAP MB51/FAGLL03 mapping profile.
3. ERPNext CSV mapping profile.
4. Dynamics inventory/GL mapping profile.
5. Studio exception filtering.
6. Multi-period comparison design.
7. Rule-pack schema reference.
8. Benchmark dataset expansion.
9. Evidence reviewer workflow design.
10. Manufacturing WIP scenario expansion.

## README Launch Checklist

- Include maturity note.
- Include no-cloud-upload statement.
- Include quick start.
- Include demo commands.
- Include control packs.
- Include evidence binder.
- Include anonymizer.
- Include screenshots or report previews.

## Screenshots Checklist

- Management pack executive summary.
- Static dashboard.
- Evidence binder index.
- Studio exceptions page.
- Benchmark HTML report.

## Demo GIF Plan

Record a short terminal flow: validate, reconcile, run rules, generate evidence, open Studio.

## Contributor Onboarding Plan

Start contributors with docs, tests, rule packs, and synthetic data scenarios before connector work.

## LinkedIn Launch Draft

I’m releasing ReconForge ERP, an early-stage open-source ERP reconciliation and audit intelligence toolkit.

It helps teams compare stock movements, GL entries, work orders, WIP, invoices, purchase flows, and operational controls from Odoo, SAP-style exports, and generic CSV/Excel data. The goal is to make inventory-to-finance reconciliation more repeatable, local-first, and audit-friendly for finance controllers, ERP consultants, auditors, stores teams, and workshop managers.

The project includes a CLI, sample data, Excel/HTML reports, YAML control packs, risk scoring, anonymization, synthetic data generation, benchmark outputs, Docker support, CI, and documentation.

It is new, but it addresses a real problem I have seen in ERP and accounting operations: the missing audit layer between inventory activity and financial accounting.

## Reddit / Odoo Forum Draft

I’m building ReconForge ERP, an open-source local-first toolkit for reconciling ERP exports. It is especially relevant when Odoo stock moves, valuation layers, account move lines, work orders, invoices, and purchase flows need to be compared outside the production system.

The current version supports CSV/Excel inputs, validation, stock-vs-GL matching, work-order controls, WIP aging, Excel/HTML reports, YAML control packs, anonymization, synthetic data, benchmarks, and audit evidence folders.

I would appreciate feedback from Odoo implementers and accountants on export mappings, stock valuation edge cases, and controls that should be included in future packs.

## Hacker News Style Launch Draft

Show HN: ReconForge ERP, an open-source ERP reconciliation toolkit for stock, GL, WIP, and work orders

ReconForge ERP is a local-first Python tool for reconciling ERP exports. It compares stock movements with GL entries, checks work-order and spare-part controls, reports WIP aging, runs YAML control packs, anonymizes sensitive exports, generates synthetic benchmark data, and creates audit evidence folders.

The project is early-stage but fully runnable locally with sample data, tests, Docker, CI, and documentation. It is aimed at accountants, ERP consultants, auditors, inventory managers, and workshop teams who still do a lot of this work in spreadsheets.

## Product Hunt Future Launch Note

Product Hunt is better suited after ReconForge Studio has a more polished screenshot flow and a few community mapping packs. The open-source launch should happen on GitHub first, with practical documentation and real sample outputs.
