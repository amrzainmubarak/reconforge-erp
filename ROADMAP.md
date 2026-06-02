# Roadmap

ReconForge ERP v0.2.0 expands the project into a local-first ERP reconciliation and audit intelligence platform. Future work should deepen practical ERP coverage while keeping the open-source core useful.

## Recently Added in v0.3.0

- Advanced rule operators and rule explanations.
- Fifteen control packs with risk models.
- Evidence register, binder index, and review forms.
- Risk intelligence package.
- Matching strategies and richer match explanations.
- AI-ready offline exception explanation.
- Plugin/connector foundation.
- Expanded market/category/security/privacy documentation.

## Added in v0.2.0

- YAML rule engine and reusable control packs.
- Audit evidence binder.
- Referential-integrity preserving anonymizer.
- Synthetic data generator.
- Benchmark engine with Pandas and optional DuckDB support.
- ReconForge Studio local web interface.
- Market, strategy, architecture, playbook, launch, and application documentation.
- Security workflow, CodeQL workflow, Dependabot, and pre-commit configuration.

## Next 90 Days

- Odoo stock valuation and `account.move.line` mapping templates.
- SAP MB51, FAGLL03, and FBL3N export mapping profiles.
- Inventory valuation bridge for stock valuation layer to GL reconciliation.
- Reviewer status fields in evidence binder outputs.
- Better Studio exception filtering and evidence links.
- Benchmark datasets for 10k and 100k row synthetic exports.

## 6 to 12 Months

- Native Odoo connector or guided export assistant.
- ERPNext mapping profile.
- NetSuite mapping profile.
- Multi-company and multi-warehouse support.
- Recurring-period exception tracking.
- Role-based review workflow for finance, stores, workshop, and audit users.
- Local evidence attachment model.

## Longer-Term

- Self-hosted Pro review workflow.
- Optional packaged desktop distribution.
- Connector SDK for community ERP mappings.
- Anomaly detection for unusual issue values, repeated manual journals, and high-risk workshops.
- Period-close control checklist integration.

## Product Guardrails

- Keep core reconciliation local-first.
- Avoid fake adoption claims.
- Keep controls explainable and testable.
- Keep generated data synthetic or anonymized.
- Prioritize inventory-to-GL, WIP, work-order, and audit evidence workflows over generic accounting breadth.
