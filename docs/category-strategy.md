# Category Strategy

## Product Category Definition

ReconForge ERP defines a focused category: local-first ERP reconciliation and audit intelligence. It is not an ERP, close suite, BI dashboard, or generic data-quality framework. It is the audit layer between inventory operations and financial accounting.

## Why This Category Matters

Inventory, spare parts, workshops, WIP, and purchase flows create accounting risk when operational records and GL postings diverge. Many teams still resolve these gaps through spreadsheets during close or audit.

## Why Existing Tools Leave a Gap

Enterprise close platforms focus on close orchestration and balance-sheet reconciliation. ERP systems hold source data but may not provide independent export-based audit workflows. Data-quality tools validate fields but do not ship ERP control logic. Excel is flexible but weakly governed.

## Why ReconForge Has a Credible Opening

ReconForge can be useful immediately from CSV/XLSX exports, runs locally, is open source, includes practical control packs, and speaks to finance, stores, workshops, auditors, and ERP consultants.

## Beachhead Market

Odoo/SAP export-based reconciliation for companies with inventory, spare parts, workshops, fleet maintenance, manufacturing WIP, or service operations.

## Expansion Markets

- ERPNext and NetSuite CSV workflows.
- Microsoft Dynamics export reconciliation.
- Audit firms standardizing stock-to-GL testing.
- Fleet and dealership service control packs.
- Manufacturing WIP and inventory valuation checks.

## Long-Term Platform Vision

Local-first ERP audit intelligence for finance, operations, and internal control teams.

## Open-Source Adoption Strategy

Keep the core useful, documented, and safe. Publish practical playbooks, realistic synthetic data, anonymization tools, and control packs that consultants can adapt.

## Commercialization Strategy

Offer paid self-hosted workflow, implementation services, mapping packs, training, support subscriptions, and audit-pack services while preserving a capable community edition.

## Community Strategy

Invite accountants, auditors, ERP consultants, Odoo implementers, SAP users, data engineers, and maintainers to contribute rule packs, mapping templates, and anonymized scenarios.

## Technical Moat

The moat is not one algorithm. It is the combination of explainable matching, control packs, evidence binders, anonymization, synthetic data, local Studio, and domain-specific documentation.

## Data Moat Without Owning Customer Data

ReconForge should not collect customer data. Instead, it can build a moat through synthetic scenario libraries, anonymized community examples, mapping templates, and rule-pack expertise.

## Channel Strategies

- Consultant ecosystem: reusable export mapping and control packs.
- Odoo partners: implementation validation and stock valuation checks.
- Audit firms: standardized evidence binders and repeatable audit tests.
- ERP implementation partners: pre-go-live and post-migration reconciliation.

## Execution Plans

### 90 Days

- Publish v0.3.0 with 15 control packs.
- Add screenshots from generated local outputs.
- Open mapping-template issues.
- Improve Studio filtering and evidence links.

### 6 Months

- Add Odoo/SAP column mapper profiles.
- Add recurring-period comparison.
- Add reviewer status fields and exception lifecycle.
- Publish benchmark datasets at 10k and 100k rows.

### 12 Months

- Add read-only connector SDK examples.
- Launch self-hosted review workflow pilot.
- Add ERPNext/NetSuite/Dynamics CSV profiles.
- Build community pack review process.

## What Must Be True To Become Category Leader

- The CLI and Studio must remain reliable.
- Control packs must be practical and trusted.
- Documentation must be understandable by non-developers.
- Sample data and anonymization must make evaluation easy.
- The community must see honest, useful domain work rather than inflated claims.

## Risks That Could Kill The Project

- Becoming too broad.
- Shipping fragile connectors too early.
- Failing to protect sensitive data.
- Looking like a spreadsheet wrapper.
- Neglecting tests and documentation.
- Overstating maturity.

## Avoid Becoming Just Another Excel Tool

Focus on repeatability, evidence, rule packs, risk scoring, anonymization, benchmarks, and auditable outputs. Excel can remain an output format; it should not be the control system.
